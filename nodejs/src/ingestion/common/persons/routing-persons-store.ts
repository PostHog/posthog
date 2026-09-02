import { DateTime } from 'luxon'

import { errorClassLabel } from '~/common/personhog/metrics'
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
 * Fails startup when a non-pg mode is missing the endpoints it dials:
 * one loud boot error instead of every write failing.
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
 * Whether two property maps say the same thing, compared by value so a
 * rebuilt nested object does not read as a difference.
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
 * Key-order-insensitive equality, because Postgres jsonb reorders object
 * keys while personhog answers in write order. Array order stays
 * significant because it is significant to the customer's data.
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
 * How long one shadow verb may run before the batch stops waiting on it.
 * Above the personhog merge deadline so a first attempt is never cut
 * short, and far enough under the consumer's poll interval that one
 * degraded verb cannot cost the group its membership.
 */
const SHADOW_VERB_TIMEOUT_MS = 60_000

/** Raised when a shadow verb outruns its ceiling and the batch abandons it. */
class ShadowVerbTimeoutError extends Error {
    constructor(verb: string) {
        super(`personhog shadow ${verb} exceeded ${SHADOW_VERB_TIMEOUT_MS}ms and was abandoned`)
        this.name = 'ShadowVerbTimeoutError'
    }
}

/**
 * Routes person-store verbs between the backends: personhog mode sends
 * every verb to the personhog store; shadow runs Postgres as the
 * authoritative result with the personhog call after it, counted but
 * never failing the batch. Each backend runs its own whole merge.
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
     * Runs the personhog side of a shadowed verb: sequential, awaited,
     * never allowed to fail the batch. Awaited means its wall clock spends
     * the consumer's poll budget, so a verb that outruns the ceiling is
     * abandoned and counted as lost fidelity; the bound is per verb.
     */
    private async shadowed(verb: string, run: () => Promise<unknown>): Promise<void> {
        let timer: ReturnType<typeof setTimeout> | undefined
        const running = run()
        // The abandoned leg keeps running against the personhog side; its
        // settlement is swallowed here so a rejection arriving after the
        // ceiling cannot surface as an unhandled one.
        void running.catch(() => {})
        try {
            await Promise.race([
                running,
                new Promise<never>((_resolve, reject) => {
                    timer = setTimeout(() => reject(new ShadowVerbTimeoutError(verb)), SHADOW_VERB_TIMEOUT_MS)
                }),
            ])
        } catch (error) {
            // Labelled by class as well as verb: the failures a rollout
            // must tell apart read identically under one number.
            personhogStoreShadowErrorsCounter.labels({ verb, error: errorClassLabel(error) }).inc()
            logger.warn('personhog shadow verb failed', { verb, error: String(error) })
        } finally {
            clearTimeout(timer)
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
     * A comparator that throws is a bug in the comparator; counting it
     * among shadow failures would blame the thing under judgment.
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
     * Records whether the shadow backend answered the same person. Row ids
     * are not compared because the backends allocate independently; the
     * uuid is derived the same way on both.
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
                // Which side is empty is the whole question: personhog
                // missing a person fades; losing one never does.
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
     * The caller holds the Postgres row, whose numeric id means nothing
     * here (independent sequences), so a shadow write re-resolves by
     * distinct id and skips, counted, when the person does not exist yet.
     * Memoized per batch.
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
     * Merges are distinct-id addressed, so no re-resolution: the same
     * request replays the whole merge against this backend's own graph.
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
     * The survivor decides where every later event lands, so a verdict
     * disagreement is the most consequential divergence; the vocabularies
     * differ between backends, so a difference is a finding, not an alarm.
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
        // Release runs in the pipeline's finally, where shadow must not
        // throw; the batch is already acked, so kept segments would
        // accumulate without bound through an outage.
        try {
            this.personhog.abandonBatch(batchId)
        } catch (error) {
            personhogStoreShadowErrorsCounter.labels({ verb: 'releaseBatch', error: errorClassLabel(error) }).inc()
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
                // The store's unwritten-lanes rejection is the right alarm
                // only when it owns the data; a shadow-only fault must not
                // stop shutdown.
                await this.shadowed('shutdown', () => this.personhog.shutdown())
            }
        }
    }
}
