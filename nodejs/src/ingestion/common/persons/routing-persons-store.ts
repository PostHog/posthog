import { ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { grpcErrorType } from '~/common/personhog/metrics'
import {
    personhogStoreShadowCompareFailedCounter,
    personhogStoreShadowComparedCounter,
    personhogStoreShadowDivergenceCounter,
    personhogStoreShadowErrorsCounter,
    personhogStoreShadowSkipsCounter,
} from '~/common/persons/metrics'
import { PersonMessage } from '~/common/persons/person-message'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult } from '~/common/utils/db/db'
import { logger } from '~/common/utils/logger'
import { BatchWritingStoreFlushStats } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt } from '~/types'

import { EventOps } from './person-update'
import { PersonhogPersonsStore } from './personhog-persons-store'
import { FlushResult, MergePersonsRequest, MergePersonsResult, PersonsBackend, PersonsStore } from './persons-store'
import { BatchBoundPersonsStore, PersonsStoreForBatch } from './persons-store-for-batch'

export type PersonsStoreMode = 'pg' | 'personhog' | 'shadow'

export function parsePersonsStoreMode(raw: string): PersonsStoreMode {
    if (raw === 'pg' || raw === 'personhog' || raw === 'shadow') {
        return raw
    }
    throw new Error(`PERSONS_STORE_MODE must be pg, personhog, or shadow; got ${JSON.stringify(raw)}`)
}

/**
 * Fails startup when a non-pg mode is missing the endpoints it dials,
 * so a misconfiguration is one loud boot error instead of every write
 * failing at its first RPC.
 */
export function assertPersonsStoreModeConfig(
    mode: PersonsStoreMode,
    addrs: { routerAddr: string; identityAddr: string }
): void {
    if (mode === 'pg') {
        return
    }
    const missing = [
        ...(addrs.routerAddr ? [] : ['PERSONHOG_ADDR']),
        ...(addrs.identityAddr ? [] : ['PERSONHOG_IDENTITY_ADDR']),
    ]
    if (missing.length > 0) {
        throw new Error(`PERSONS_STORE_MODE=${mode} requires ${missing.join(' and ')} to be set`)
    }
}

/**
 * Whether two property maps say the same thing. Compared by serialised value
 * rather than by reference so a nested object that was rebuilt on one side
 * does not read as a difference.
 */
function propertiesMatch(left: Properties, right: Properties): boolean {
    const leftKeys = Object.keys(left ?? {})
    const rightKeys = Object.keys(right ?? {})
    if (leftKeys.length !== rightKeys.length) {
        return false
    }
    return leftKeys.every((key) => key in (right ?? {}) && stableEqual(left[key], right[key]))
}

/**
 * Key-order-insensitive structural equality for JSON property values, because
 * Postgres jsonb reorders object keys while personhog answers in write order,
 * so a serialised comparison would flag every nested object. Array order
 * stays significant because it is significant to the customer's data.
 */
function stableEqual(left: unknown, right: unknown): boolean {
    if (left === right) {
        return true
    }
    if (Array.isArray(left) || Array.isArray(right)) {
        return (
            Array.isArray(left) &&
            Array.isArray(right) &&
            left.length === right.length &&
            left.every((entry, index) => stableEqual(entry, right[index]))
        )
    }
    if (typeof left !== 'object' || typeof right !== 'object' || left === null || right === null) {
        return false
    }
    const leftKeys = Object.keys(left)
    const rightKeys = Object.keys(right)
    return (
        leftKeys.length === rightKeys.length &&
        leftKeys.every(
            (key) =>
                Object.prototype.hasOwnProperty.call(right, key) &&
                stableEqual((left as Record<string, unknown>)[key], (right as Record<string, unknown>)[key])
        )
    )
}

/** The property names that differ, for a log that must not carry their values. */
function differingKeys(left: Properties, right: Properties): string[] {
    const names = new Set([...Object.keys(left ?? {}), ...Object.keys(right ?? {})])
    return [...names].filter((key) => !stableEqual((left ?? {})[key], (right ?? {})[key])).sort()
}

/**
 * A bounded metric label for a shadow failure. Every gRPC fault arrives as
 * the same ConnectError class, so those are labelled by status code and
 * everything else by its class name.
 */
function errorClass(error: unknown): string {
    if (error instanceof ConnectError) {
        return grpcErrorType(error)
    }
    const name = error instanceof Error ? error.constructor?.name : undefined
    return typeof name === 'string' && name.length > 0 && name.length <= 64 ? name : 'unknown'
}

/**
 * Routes person-store verbs between the Postgres backend and the personhog
 * one: personhog mode sends every verb to the personhog store, and shadow
 * runs the Postgres call as the authoritative result with the personhog
 * call after it, its failures counted but never failing the batch. Merges
 * route through `mergePersons` like any other verb, each backend running
 * its own whole merge, so shadow rehearses every merge (folds included)
 * against the personhog backend's own graph.
 */
export class RoutingPersonsStore implements PersonsStore {
    constructor(
        private pg: PersonsStore,
        private personhog: PersonhogPersonsStore,
        private mode: 'personhog' | 'shadow'
    ) {}

    // Shadow mode's personhog calls never reach a caller, so the errors a
    // caller sees are the authoritative side's.
    get backend(): PersonsBackend {
        return this.mode === 'shadow' ? this.pg.backend : this.personhog.backend
    }

    /**
     * Run the personhog side of a shadowed verb: sequential, awaited, and
     * never allowed to fail the batch.
     */
    private async shadowed(verb: string, run: () => Promise<unknown>): Promise<void> {
        try {
            await run()
        } catch (error) {
            // Labelled by class as well as verb: a fence timeout, a size
            // rejection, and the identity service being unreachable are the
            // three things a rollout most needs to tell apart, and one
            // number for all of them cannot.
            personhogStoreShadowErrorsCounter.labels({ verb, error: errorClass(error) }).inc()
            logger.warn('personhog shadow verb failed', { verb, error: String(error) })
        }
    }

    /**
     * The whole mode semantics, once: personhog mode runs the personhog
     * call, shadow runs pg as the authoritative result and the personhog
     * call after it, swallowed.
     */
    private async route<T>(
        verb: string,
        pg: () => Promise<T>,
        personhog: () => Promise<T>,
        opts?: { shadow?: () => Promise<unknown>; compare?: (authoritative: T, shadow: unknown) => void }
    ): Promise<T> {
        if (this.mode === 'personhog') {
            return personhog()
        }
        const result = await pg()
        await this.shadowed(verb, async () => {
            const shadow = await (opts?.shadow ?? personhog)()
            this.compared(verb, () => opts?.compare?.(result, shadow))
        })
        return result
    }

    /**
     * Runs a comparison without letting it speak for the backend. A
     * comparator that throws is a bug in the comparator, and counting it
     * among the shadow backend's failures would blame the thing the rollout
     * is trying to judge.
     */
    private compared(verb: string, run: () => void): void {
        try {
            run()
        } catch (error) {
            personhogStoreShadowCompareFailedCounter.labels({ verb }).inc()
            logger.warn('personhog shadow comparison failed', { verb, error: String(error) })
        }
    }

    /**
     * Records whether the shadow backend answered the same person as the
     * authoritative one, which is the divergence signal the error counter
     * cannot carry. Row ids are not compared because the backends allocate
     * from independent sequences; the uuid is the identifier both derive
     * the same way.
     */
    private comparePerson(verb: string, authoritative: unknown, shadow: unknown): void {
        // Absence arrives as null from either backend, and as undefined from
        // a caller that answered nothing at all; both mean the same thing
        // here and neither may be dereferenced.
        const left = (authoritative ?? null) as InternalPerson | null
        const right = (shadow ?? null) as InternalPerson | null
        personhogStoreShadowComparedCounter.labels({ verb }).inc()
        if (left === null || right === null) {
            if (left !== right) {
                // Which side is empty is the whole question early in a
                // rollout: personhog not having seen a person yet is
                // expected and fades, while personhog losing one that
                // Postgres still has never is.
                this.recordDivergence(verb, left === null ? 'missing_authoritative' : 'missing_shadow', {
                    authoritative: left?.uuid ?? null,
                    shadow: right?.uuid ?? null,
                })
            }
            return
        }
        if (left.uuid !== right.uuid) {
            this.recordDivergence(verb, 'uuid', { authoritative: left.uuid, shadow: right.uuid })
        }
        if (left.is_identified !== right.is_identified) {
            this.recordDivergence(verb, 'is_identified', {
                authoritative: left.is_identified,
                shadow: right.is_identified,
            })
        }
        if (!propertiesMatch(left.properties, right.properties)) {
            this.recordDivergence(verb, 'properties', {
                uuid: left.uuid,
                // Key names only. Values are customer data and this log is
                // not the place for it; the names are enough to find the
                // event that wrote them.
                differing: differingKeys(left.properties, right.properties),
            })
        }
    }

    private recordDivergence(verb: string, field: string, details: Record<string, unknown>): void {
        personhogStoreShadowDivergenceCounter.labels({ verb, field }).inc()
        logger.warn('personhog shadow answered differently from the authoritative backend', {
            verb,
            field,
            ...details,
        })
    }

    /**
     * Resolve the personhog backend's own person for a shadowed write. The
     * caller holds the Postgres row, whose numeric id means nothing in
     * the personhog backend — the two id sequences are independent — so a
     * shadow write must re-resolve by distinct id and skip, counted,
     * when the person does not exist there yet. The fetch memoizes per
     * batch, so repeated writes to one person cost one resolution.
     */
    private async withShadowPerson(
        verb: string,
        teamId: number,
        distinctId: string,
        batchId: number,
        run: (person: InternalPerson) => Promise<unknown>
    ): Promise<void> {
        const shadowPerson = await this.personhog.fetchForUpdate(teamId, distinctId, batchId)
        if (shadowPerson === null) {
            personhogStoreShadowSkipsCounter.labels({ verb }).inc()
            return
        }
        await run(shadowPerson)
    }

    forBatch(batchId: number): PersonsStoreForBatch {
        return new BatchBoundPersonsStore(this, batchId)
    }

    fetchForChecking(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        return this.route(
            'fetchForChecking',
            () => this.pg.fetchForChecking(teamId, distinctId, batchId),
            () => this.personhog.fetchForChecking(teamId, distinctId, batchId),
            { compare: (authoritative, shadow) => this.comparePerson('fetchForChecking', authoritative, shadow) }
        )
    }

    fetchForUpdate(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        return this.route(
            'fetchForUpdate',
            () => this.pg.fetchForUpdate(teamId, distinctId, batchId),
            () => this.personhog.fetchForUpdate(teamId, distinctId, batchId),
            { compare: (authoritative, shadow) => this.comparePerson('fetchForUpdate', authoritative, shadow) }
        )
    }

    createPerson(
        createdAt: DateTime,
        properties: Properties,
        propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        isUserId: number | null,
        isIdentified: boolean,
        uuid: string,
        primaryDistinctId: { distinctId: string; version?: number },
        extraDistinctIds: { distinctId: string; version?: number }[] | undefined,
        tx: PersonRepositoryTransaction | undefined,
        batchId: number
    ): Promise<CreatePersonResult> {
        return this.route(
            'createPerson',
            () =>
                this.pg.createPerson(
                    createdAt,
                    properties,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    teamId,
                    isUserId,
                    isIdentified,
                    uuid,
                    primaryDistinctId,
                    extraDistinctIds,
                    tx,
                    batchId
                ),
            () =>
                this.personhog.createPerson(
                    createdAt,
                    properties,
                    propertiesLastUpdatedAt,
                    propertiesLastOperation,
                    teamId,
                    isUserId,
                    isIdentified,
                    uuid,
                    primaryDistinctId,
                    extraDistinctIds,
                    tx,
                    batchId
                )
        )
    }

    applyEventOps(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string,
        batchId: number
    ): Promise<[InternalPerson, PersonMessage[]]> {
        return this.route(
            'applyEventOps',
            () => this.pg.applyEventOps(person, ops, distinctId, batchId),
            () => this.personhog.applyEventOps(person, ops, distinctId, batchId),
            {
                shadow: () =>
                    this.withShadowPerson('applyEventOps', person.team_id, distinctId, batchId, (shadowPerson) =>
                        this.personhog.applyEventOps(shadowPerson, ops, distinctId, batchId)
                    ),
            }
        )
    }

    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        batchId: number,
        forceUpdate?: boolean,
        tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return this.route(
            'updatePersonWithPropertiesDiffForUpdate',
            () =>
                this.pg.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    propertiesToSet,
                    propertiesToUnset,
                    otherUpdates,
                    distinctId,
                    batchId,
                    forceUpdate,
                    tx
                ),
            () =>
                this.personhog.updatePersonWithPropertiesDiffForUpdate(
                    person,
                    propertiesToSet,
                    propertiesToUnset,
                    otherUpdates,
                    distinctId,
                    batchId,
                    forceUpdate,
                    tx
                ),
            {
                shadow: () =>
                    this.withShadowPerson(
                        'updatePersonWithPropertiesDiffForUpdate',
                        person.team_id,
                        distinctId,
                        batchId,
                        (shadowPerson) =>
                            this.personhog.updatePersonWithPropertiesDiffForUpdate(
                                shadowPerson,
                                propertiesToSet,
                                propertiesToUnset,
                                otherUpdates,
                                distinctId,
                                batchId,
                                forceUpdate
                            )
                    ),
            }
        )
    }

    /**
     * Merges are distinct-id addressed, so the personhog side needs no
     * person re-resolution: the same request replays the whole merge
     * against that backend's saga, keeping the shadow graph's topology in
     * step with the Postgres one.
     */
    mergePersons(request: MergePersonsRequest, batchId: number): Promise<MergePersonsResult> {
        return this.route(
            'mergePersons',
            () => this.pg.mergePersons(request, batchId),
            () => this.personhog.mergePersons(request, batchId),
            { compare: (authoritative, shadow) => this.compareMerge(authoritative, shadow) }
        )
    }

    /**
     * Records whether the two backends reached the same merge verdict; the
     * survivor decides which person every later event in the batch lands on,
     * so a disagreement here is the most consequential shadow can surface.
     * The outcome vocabularies are not identical between backends (see the
     * parity notes), so an outcome difference is a finding to read rather
     * than an alarm by itself.
     */
    private compareMerge(authoritative: unknown, shadow: unknown): void {
        const left = authoritative as MergePersonsResult
        const right = shadow as MergePersonsResult
        personhogStoreShadowComparedCounter.labels({ verb: 'mergePersons' }).inc()
        if ((left.survivor?.uuid ?? null) !== (right.survivor?.uuid ?? null)) {
            this.recordDivergence('mergePersons', 'survivor', {
                authoritative: left.survivor?.uuid ?? null,
                shadow: right.survivor?.uuid ?? null,
            })
        }
        const shadowOutcomes = new Map(right.results.map((source) => [source.sourceDistinctId, source.outcome]))
        for (const source of left.results) {
            const other = shadowOutcomes.get(source.sourceDistinctId)
            if (other !== source.outcome) {
                this.recordDivergence('mergePersons', 'outcome', {
                    authoritative: source.outcome,
                    shadow: other ?? null,
                })
            }
        }
    }

    personPropertiesSize(personId: string, teamId: number): Promise<number> {
        return this.route(
            'personPropertiesSize',
            () => this.pg.personPropertiesSize(personId, teamId),
            () => this.personhog.personPropertiesSize(personId, teamId)
        )
    }

    prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void> {
        return this.route(
            'prefetchPersons',
            () => this.pg.prefetchPersons(teamDistinctIds),
            () => this.personhog.prefetchPersons(teamDistinctIds)
        )
    }

    getFlushStats(): BatchWritingStoreFlushStats {
        const pg = this.pg.getFlushStats()
        const personhog = this.personhog.getFlushStats()
        return {
            dirtyEntryCount: pg.dirtyEntryCount + personhog.dirtyEntryCount,
            // Both stores see the same batches in shadow mode, so batch
            // references overlap rather than add; entries and cache
            // slots are per-store and sum.
            referencedBatchCount: Math.max(pg.referencedBatchCount, personhog.referencedBatchCount),
            cacheEntryCount: pg.cacheEntryCount + personhog.cacheEntryCount,
        }
    }

    flush(): Promise<FlushResult[]> {
        return this.route(
            'flush',
            () => this.pg.flush(),
            () => this.personhog.flush()
        )
    }

    releaseBatch(batchId: number): void {
        this.pg.releaseBatch(batchId)
        if (this.mode === 'personhog') {
            this.personhog.releaseBatch(batchId)
            return
        }
        // Release runs in the pipeline's finally, where the shadow backend
        // must not throw. Abandon rather than keep: the batch is already
        // acked on the authoritative side, so segments kept here would
        // accumulate without bound through an identity outage.
        try {
            this.personhog.abandonBatch(batchId)
        } catch (error) {
            personhogStoreShadowErrorsCounter.labels({ verb: 'releaseBatch', error: errorClass(error) }).inc()
            logger.warn('personhog shadow release failed', { batchId, error: String(error) })
        }
    }

    async shutdown(): Promise<void> {
        try {
            await this.pg.shutdown()
        } finally {
            if (this.mode === 'personhog') {
                await this.personhog.shutdown()
            } else {
                // The personhog store rejects when lanes still hold unwritten
                // ops, which is the right alarm when it owns the data and the
                // wrong one when it does not: a shadow-only fault must not
                // stop the process from shutting down cleanly.
                await this.shadowed('shutdown', () => this.personhog.shutdown())
            }
        }
    }
}
