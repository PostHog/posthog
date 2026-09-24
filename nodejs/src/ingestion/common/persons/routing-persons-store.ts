import { ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { errorClassLabel } from '~/common/personhog/metrics'
import {
    personhogStoreShadowCompareFailedCounter,
    personhogStoreShadowComparedCounter,
    personhogStoreShadowDivergenceCounter,
    personhogStoreShadowDurationSeconds,
    personhogStoreShadowErrorsCounter,
    personhogStoreShadowFoldRedriveCounter,
    personhogStoreShadowSkipsCounter,
} from '~/common/persons/metrics'
import { PersonMessage } from '~/common/persons/person-message'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult } from '~/common/utils/db/db'
import { logger } from '~/common/utils/logger'
import { promiseRetry } from '~/common/utils/retries'
import { BatchWritingStoreFlushStats } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt } from '~/types'

import { EventOps } from './person-update'
import { PersonhogPersonsStore } from './personhog-persons-store'
import {
    FlushResult,
    MergePersonsRequest,
    MergePersonsResult,
    PersonsBackend,
    PersonsStore,
    isFoldRequest,
} from './persons-store'
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
 * Routes person-store verbs between the Postgres backend and the personhog
 * one. The mode applies to the whole deployment: personhog sends every
 * verb to the personhog store, and shadow runs the Postgres call as the
 * authoritative result with the personhog call after it, its failures
 * counted and logged but never failing the batch. Merges route through
 * `mergePersons` like any other verb: each backend runs its own whole
 * merge (the identity service's saga, or the Postgres store's own), so
 * shadow mode rehearses every merge, folds included, against the
 * personhog backend's own graph; a fold only the shadow aborted is
 * re-driven per pair.
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
    private async shadowed(verb: string, run: (abandoned: AbortSignal) => Promise<unknown>): Promise<void> {
        const stopTimer = personhogStoreShadowDurationSeconds.labels({ verb }).startTimer()
        let timer: ReturnType<typeof setTimeout> | undefined
        const abandon = new AbortController()
        const running = run(abandon.signal)
        // The abandoned leg keeps running against the personhog side; its
        // settlement is swallowed here so a rejection arriving after the
        // ceiling cannot surface as an unhandled one.
        void running.catch(() => {})
        try {
            await Promise.race([
                running,
                new Promise<never>((_resolve, reject) => {
                    timer = setTimeout(() => {
                        abandon.abort()
                        reject(new ShadowVerbTimeoutError(verb))
                    }, SHADOW_VERB_TIMEOUT_MS)
                }),
            ])
        } catch (error) {
            this.recordShadowFailure(verb, error)
        } finally {
            clearTimeout(timer)
            stopTimer()
        }
    }

    private recordShadowFailure(verb: string, error: unknown): void {
        // Labelled by class as well as verb: the failures a rollout
        // must tell apart read identically under one number.
        personhogStoreShadowErrorsCounter.labels({ verb, error: errorClassLabel(error) }).inc()
        logger.warn('personhog shadow verb failed', { verb, error: String(error) })
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
        opts?: {
            shadow?: (abandoned: AbortSignal) => Promise<unknown>
            compare?: (authoritative: T, shadow: unknown) => void
            after?: (authoritative: T, shadow: unknown, abandoned: AbortSignal) => Promise<void>
        }
    ): Promise<T> {
        if (this.mode === 'personhog') {
            return personhog()
        }
        const result = await pg()
        await this.shadowed(verb, async (abandoned) => {
            const shadow = await (opts?.shadow ? opts.shadow(abandoned) : personhog())
            this.compared(verb, () => opts?.compare?.(result, shadow))
            await opts?.after?.(result, shadow, abandoned)
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
                this.recordDivergence(verb, left === null ? 'missing_authoritative' : 'missing_shadow')
            }
            return
        }
        if (left.uuid !== right.uuid) {
            this.recordDivergence(verb, 'uuid')
        }
        if (left.is_identified !== right.is_identified) {
            this.recordDivergence(verb, 'is_identified')
        }
        if (!propertiesMatch(left.properties, right.properties)) {
            this.recordDivergence(verb, 'properties')
        }
    }

    private recordDivergence(verb: string, field: string): void {
        personhogStoreShadowDivergenceCounter.labels({ verb, field }).inc()
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
            {
                shadow: (abandoned) => this.shadowMerge(request, batchId, abandoned),
                compare: (authoritative, shadow) => this.compareMerge(authoritative, shadow),
                after: (authoritative, shadow, abandoned) =>
                    this.redriveShadowFoldPairs(request, batchId, authoritative, shadow, abandoned),
            }
        )
    }

    /** The merge service's retries wrap the routed call, which never throws for the shadow side. */
    private retriedShadowMerge(
        request: MergePersonsRequest,
        batchId: number,
        abandoned: AbortSignal
    ): Promise<MergePersonsResult> {
        return promiseRetry(
            // An abandoned verb starts no new write; one already in flight still finishes.
            () =>
                abandoned.aborted
                    ? Promise.reject(new ShadowVerbTimeoutError('mergePersons'))
                    : this.personhog.mergePersons(request, batchId),
            'shadow_merge_persons',
            undefined,
            undefined,
            undefined,
            [ConnectError, ShadowVerbTimeoutError]
        )
    }

    /** A fold is never retried as a fold: one that throws aborts, and its pairs take the re-drive. */
    private async shadowMerge(
        request: MergePersonsRequest,
        batchId: number,
        abandoned: AbortSignal
    ): Promise<MergePersonsResult> {
        if (!isFoldRequest(request)) {
            return this.retriedShadowMerge(request, batchId, abandoned)
        }
        try {
            return await this.personhog.mergePersons(request, batchId)
        } catch (error) {
            this.recordShadowFailure('mergePersons', error)
            return { survivor: null, results: [], foldAborted: 'error' }
        }
    }

    /**
     * A fold only the shadow aborted gets its pairs re-driven, as the
     * fallback merges the service cannot issue (it sees only
     * the executed authoritative result). Per-pair op ids let the pair's
     * own event attach on redelivery; ops stay empty because plan events
     * route theirs through the shadowed update path regardless.
     */
    private async redriveShadowFoldPairs(
        request: MergePersonsRequest,
        batchId: number,
        authoritative: MergePersonsResult,
        shadow: unknown,
        abandoned: AbortSignal
    ): Promise<void> {
        const shadowResult = shadow as MergePersonsResult
        if (authoritative.foldAborted !== undefined || shadowResult?.foldAborted === undefined) {
            return
        }
        for (const source of request.sources) {
            try {
                const result = await this.retriedShadowMerge(
                    {
                        teamId: request.teamId,
                        targetDistinctId: request.targetDistinctId,
                        sources: [source],
                        eventUuid: source.eventUuid,
                        eventOps: {
                            set: {},
                            setOnce: {},
                            unset: [],
                            denied: false,
                            shouldForceUpdate: false,
                            eventName: request.eventOps.eventName,
                        },
                        allowIdentifiedSources: request.allowIdentifiedSources,
                        mergeMode: request.mergeMode,
                        createdAtMs: request.createdAtMs,
                    },
                    batchId,
                    abandoned
                )
                const outcome = result.results[0]?.outcome ?? 'error'
                personhogStoreShadowFoldRedriveCounter.labels({ outcome }).inc()
                if (outcome !== 'merged' && outcome !== 'attached' && outcome !== 'noop_same_person') {
                    // Named so a row comparison can exclude exactly these
                    // pairs; the pair's next event re-attempts organically.
                    logger.warn('shadow fold re-drive left the pair unmerged', {
                        team_id: request.teamId,
                        source_distinct_id: source.distinctId,
                        target_distinct_id: request.targetDistinctId,
                        outcome,
                    })
                }
            } catch (error) {
                personhogStoreShadowFoldRedriveCounter.labels({ outcome: errorClassLabel(error) }).inc()
                logger.warn('shadow fold re-drive left the pair unmerged', {
                    team_id: request.teamId,
                    source_distinct_id: source.distinctId,
                    target_distinct_id: request.targetDistinctId,
                    outcome: errorClassLabel(error),
                })
            }
        }
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
        // An aborted fold carries no verdicts, so the disposition itself is
        // what the backends can disagree on: one record when only one side
        // aborted, nothing when both did.
        if (left.foldAborted || right.foldAborted) {
            const onlyOneAborted = (left.foldAborted === undefined) !== (right.foldAborted === undefined)
            if (onlyOneAborted) {
                this.recordDivergence('mergePersons', 'fold_disposition')
            }
            return
        }
        if ((left.survivor?.uuid ?? null) !== (right.survivor?.uuid ?? null)) {
            this.recordDivergence('mergePersons', 'survivor')
        }
        const shadowOutcomes = new Map(right.results.map((source) => [source.sourceDistinctId, source.outcome]))
        for (const source of left.results) {
            const other = shadowOutcomes.get(source.sourceDistinctId)
            if (other !== source.outcome) {
                this.recordDivergence('mergePersons', 'outcome')
            }
            shadowOutcomes.delete(source.sourceDistinctId)
        }
        // A verdict for a source Postgres never reported is a divergence too.
        shadowOutcomes.forEach(() => this.recordDivergence('mergePersons', 'outcome'))
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
