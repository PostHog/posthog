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
    personhogStoreShadowMergeRedriveCounter,
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

import { PersonMergeCallFailedError, PersonMergeUnsettledError } from './person-merge-types'
import { EventOps } from './person-update'
import { CREATE_EVENT_NAME, PersonhogPersonsStore } from './personhog-persons-store'
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

/**
 * A deferred shadow merge waits this long before a flush re-drives it, since the op holding its person usually
 * completes within it, and stays in play for the identity service's execute timeout for that op.
 */
const SHADOW_MERGE_REDRIVE_DELAY_MS = 5_000
const SHADOW_MERGE_REDRIVE_WINDOW_MS = 30_000
/** Re-drives one flush runs, and deferred merges one store keeps; past them the oldest are dropped, counted. */
const SHADOW_MERGE_REDRIVES_PER_FLUSH = 16
const SHADOW_MERGE_DEFERRED_LIMIT = 1_000

type DeferredShadowMerge = { request: MergePersonsRequest; batchId: number; notBefore: number; expiresAt: number }

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
    private comparePerson(
        verb: string,
        authoritative: unknown,
        shadow: unknown,
        compareProperties: boolean = true
    ): void {
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
        if (compareProperties && !propertiesMatch(left.properties, right.properties)) {
            this.recordDivergence(verb, 'properties')
        }
    }

    private recordDivergence(verb: string, field: string): void {
        personhogStoreShadowDivergenceCounter.labels({ verb, field }).inc()
    }

    /**
     * The caller holds the Postgres row, whose numeric id means nothing
     * here (independent sequences), so a shadow write re-resolves by
     * distinct id. A person that does not exist here yet is usually one
     * another pod attached on the authoritative side while its shadow merge
     * was still running, so a caller that can hold its ops for a resolve
     * at flush does; the rest skip, counted. Memoized per batch.
     */
    private async withShadowPerson(
        verb: string,
        teamId: number,
        distinctId: string,
        batchId: number,
        run: (person: InternalPerson) => Promise<unknown>,
        hold?: () => void
    ): Promise<void> {
        // Ops still held for this id were stated earlier, so later ops queue behind them, as the event's
        // partition does when the authoritative store retries.
        if (hold && this.personhog.hasHeldOps(teamId, distinctId)) {
            hold()
            return
        }
        const shadowPerson = await this.personhog.fetchForUpdate(teamId, distinctId, batchId)
        if (shadowPerson === null) {
            if (hold) {
                hold()
                return
            }
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
            // A checking read resolves identity only: personhog answers it from the identity service without
            // the leader's document, so its properties are empty unless a projection happens to be cached, and
            // the personless step never reads them.
            {
                compare: (authoritative, shadow) =>
                    this.comparePerson('fetchForChecking', authoritative, shadow, false),
            }
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
                ),
            {
                shadow: (abandoned) =>
                    this.shadowCreate(
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
                            ),
                        teamId,
                        properties,
                        isIdentified,
                        primaryDistinctId.distinctId,
                        batchId,
                        abandoned
                    ),
                after: (authoritative, shadow, abandoned) =>
                    this.reconcileShadowCreate(
                        authoritative,
                        shadow as CreatePersonResult,
                        properties,
                        primaryDistinctId.distinctId,
                        batchId,
                        abandoned
                    ),
            }
        )
    }

    /**
     * A create the client gave up on may have left the person without its properties, and the event does not retry
     * here, so its properties are held set-once for the distinct id. A deterministic rejection would fail again, and
     * an abandoned create's batch may be released, so neither is held.
     */
    private async shadowCreate(
        create: () => Promise<CreatePersonResult>,
        teamId: number,
        properties: Properties,
        isIdentified: boolean,
        distinctId: string,
        batchId: number,
        abandoned: AbortSignal
    ): Promise<CreatePersonResult> {
        try {
            return await create()
        } catch (error) {
            if (!abandoned.aborted && (error as { isRetriable?: boolean })?.isRetriable === true) {
                this.personhog.holdEventOps(
                    teamId,
                    distinctId,
                    {
                        set: {},
                        setOnce: properties,
                        unset: [],
                        denied: false,
                        shouldForceUpdate: true,
                        eventName: CREATE_EVENT_NAME,
                        ...(isIdentified ? { isIdentified: true } : {}),
                    },
                    batchId
                )
            }
            throw error
        }
    }

    /** Postgres created the person and personhog only found it: apply the creation properties set-once. */
    private async reconcileShadowCreate(
        authoritative: CreatePersonResult,
        shadow: CreatePersonResult,
        properties: Properties,
        distinctId: string,
        batchId: number,
        abandoned: AbortSignal
    ): Promise<void> {
        if (
            abandoned.aborted ||
            !(authoritative.success && authoritative.created) ||
            !(shadow.success && !shadow.created)
        ) {
            return
        }
        const ops: EventOps = {
            set: {},
            setOnce: properties,
            unset: [],
            denied: false,
            shouldForceUpdate: true,
            eventName: CREATE_EVENT_NAME,
        }
        await this.personhog.applyEventOps(shadow.person, ops, distinctId, batchId)
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
                    this.withShadowPerson(
                        'applyEventOps',
                        person.team_id,
                        distinctId,
                        batchId,
                        (shadowPerson) => this.personhog.applyEventOps(shadowPerson, ops, distinctId, batchId),
                        () => this.personhog.holdEventOps(person.team_id, distinctId, ops, batchId)
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
                compare: (authoritative, shadow) => this.compareMerge(request, authoritative, shadow),
                after: (authoritative, shadow, abandoned) =>
                    this.redriveShadowFoldPairs(request, batchId, authoritative, shadow, abandoned),
            }
        )
    }

    /** Shadow merges whose retries ended unsettled or without a verdict, re-driven at a flush once their delay has passed. */
    private deferredShadowMerges: DeferredShadowMerge[] = []

    /**
     * The merge service's retries wrap the routed call, which never throws
     * for the shadow side. A merge still unsettled or without a verdict
     * after them is deferred to the flush, unless this is that re-drive.
     */
    private async retriedShadowMerge(
        request: MergePersonsRequest,
        batchId: number,
        abandoned: AbortSignal,
        defer: boolean = true
    ): Promise<MergePersonsResult> {
        let unsettled: MergePersonsResult | undefined
        try {
            return await promiseRetry(
                async () => {
                    // An abandoned verb starts no new write; one already in flight still finishes.
                    if (abandoned.aborted) {
                        throw new ShadowVerbTimeoutError('mergePersons')
                    }
                    const result = await this.personhog.mergePersons(request, batchId)
                    // Unsettled means a retry under the same op id may settle it.
                    if (result.results.some((source) => source.settled === false)) {
                        unsettled = result
                        throw new PersonMergeUnsettledError('shadow merge verdict is unsettled')
                    }
                    return result
                },
                'shadow_merge_persons',
                undefined,
                undefined,
                undefined,
                [ConnectError, ShadowVerbTimeoutError]
            )
        } catch (error) {
            if (error instanceof PersonMergeUnsettledError && unsettled !== undefined) {
                if (defer) {
                    this.deferShadowMerge(request, batchId)
                }
                return unsettled
            }
            if (error instanceof PersonMergeCallFailedError && defer) {
                this.deferShadowMerge(request, batchId)
            }
            throw error
        }
    }

    private deferShadowMerge(request: MergePersonsRequest, batchId: number): void {
        const now = Date.now()
        this.deferredShadowMerges.push({
            request,
            batchId,
            notBefore: now + SHADOW_MERGE_REDRIVE_DELAY_MS,
            expiresAt: now + SHADOW_MERGE_REDRIVE_WINDOW_MS,
        })
        if (this.deferredShadowMerges.length > SHADOW_MERGE_DEFERRED_LIMIT) {
            this.dropShadowMerge(this.deferredShadowMerges.shift()!, 'the store holds its limit')
        }
    }

    private dropShadowMerge(entry: DeferredShadowMerge, reason: string): void {
        personhogStoreShadowMergeRedriveCounter.labels({ outcome: 'dropped' }).inc()
        logger.warn('shadow merge dropped unsettled', {
            team_id: entry.request.teamId,
            target_distinct_id: entry.request.targetDistinctId,
            sources: entry.request.sources.map((source) => source.distinctId),
            reason,
        })
    }

    private requeueAbandonedShadowMerges(entries: DeferredShadowMerge[]): void {
        personhogStoreShadowMergeRedriveCounter.labels({ outcome: 'abandoned' }).inc(entries.length)
        this.deferredShadowMerges.push(...entries)
    }

    /** Rejects when the ceiling abandons the leg, so a loop can stop waiting on a call it cannot cancel. */
    private abandonment(abandoned: AbortSignal): Promise<never> {
        return new Promise((_resolve, reject) =>
            abandoned.addEventListener('abort', () => reject(new ShadowVerbTimeoutError('mergePersons')), {
                once: true,
            })
        )
    }

    /**
     * The identity service refuses a merge as a conflict while another op
     * holds one of its persons, and a re-drive run too soon lands inside
     * the same hold. A deferred merge runs at the first flush past its
     * delay and is dropped once its window closes; one the ceiling
     * abandons is re-queued, counted, and a flush runs a bounded number of
     * them after the lanes.
     */
    private async redriveDeferredShadowMerges(abandoned: AbortSignal): Promise<void> {
        const now = Date.now()
        for (const entry of this.deferredShadowMerges.filter((entry) => entry.expiresAt <= now)) {
            this.dropShadowMerge(entry, 'its window closed')
        }
        const live = this.deferredShadowMerges.filter((entry) => entry.expiresAt > now)
        const due = live.filter((entry) => entry.notBefore <= now).slice(0, SHADOW_MERGE_REDRIVES_PER_FLUSH)
        this.deferredShadowMerges = live.filter((entry) => !due.includes(entry))
        if (due.length === 0) {
            return
        }
        // One abort listener for the whole loop; the catch keeps it handled if no race is waiting when it fires.
        const legAbandoned = this.abandonment(abandoned)
        void legAbandoned.catch(() => {})
        for (const [index, entry] of due.entries()) {
            if (abandoned.aborted) {
                this.requeueAbandonedShadowMerges(due.slice(index))
                return
            }
            let settled = false
            // The call itself cannot be cancelled, so the loop stops waiting for it at the ceiling and the entry
            // keeps its turn; a flush's re-drives never outlive its leg.
            const attempt = this.retriedShadowMerge(entry.request, entry.batchId, abandoned, false)
            void attempt.catch(() => {})
            try {
                const result = await Promise.race([attempt, legAbandoned])
                settled = result.results.every((source) => source.settled !== false)
            } catch (error) {
                if (abandoned.aborted) {
                    this.requeueAbandonedShadowMerges(due.slice(index))
                    return
                }
                this.recordShadowFailure('mergePersons', error)
            }
            const notBefore = Date.now() + SHADOW_MERGE_REDRIVE_DELAY_MS
            if (settled) {
                personhogStoreShadowMergeRedriveCounter.labels({ outcome: 'settled' }).inc()
            } else if (notBefore >= entry.expiresAt) {
                this.dropShadowMerge(entry, 'its window closed')
            } else {
                personhogStoreShadowMergeRedriveCounter.labels({ outcome: 'deferred' }).inc()
                this.deferredShadowMerges.push({ ...entry, notBefore })
            }
        }
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
    private compareMerge(request: MergePersonsRequest, authoritative: unknown, shadow: unknown): void {
        const left = authoritative as MergePersonsResult
        const right = shadow as MergePersonsResult
        personhogStoreShadowComparedCounter.labels({ verb: 'mergePersons' }).inc()
        // Sorted by source: the backends report the same verdicts in different orders.
        const verdicts = (result: MergePersonsResult): string =>
            result.foldAborted !== undefined
                ? `aborted:${result.foldAborted}`
                : result.results
                      .map((source) => `${source.sourceDistinctId}=${source.outcome}`)
                      .sort()
                      .join(',')
        const bothAborted = left.foldAborted !== undefined && right.foldAborted !== undefined
        const disagree =
            (left.survivor?.uuid ?? null) !== (right.survivor?.uuid ?? null) || verdicts(left) !== verdicts(right)
        if (disagree && !bothAborted) {
            logger.info('personhog shadow merge verdicts differ', {
                team_id: request.teamId,
                target_distinct_id: request.targetDistinctId,
                trigger_source_distinct_id: request.triggerSourceDistinctId,
                sources: request.sources.map((source) => source.distinctId),
                pg_survivor: left.survivor?.uuid ?? null,
                pg: verdicts(left),
                personhog_survivor: right.survivor?.uuid ?? null,
                personhog: verdicts(right),
            })
        }
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
        if (this.mode === 'personhog') {
            return this.personhog.prefetchPersons(teamDistinctIds)
        }
        // Both start now: the pipeline does not await the prefetch, so a shadow prefetch started after the
        // authoritative one finishes would lose the race with the batch's own reads.
        const shadow = this.shadowed('prefetchPersons', () => this.personhog.prefetchPersons(teamDistinctIds))
        return Promise.all([this.pg.prefetchPersons(teamDistinctIds), shadow]).then(() => undefined)
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
            () => this.personhog.flush(),
            {
                shadow: async (abandoned) => {
                    // The lanes first; the re-drives take what is left of the ceiling.
                    const flushed = await this.personhog.flush()
                    await this.redriveDeferredShadowMerges(abandoned)
                    return flushed
                },
            }
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
                if (this.deferredShadowMerges.length > 0) {
                    personhogStoreShadowMergeRedriveCounter
                        .labels({ outcome: 'dropped' })
                        .inc(this.deferredShadowMerges.length)
                    logger.warn('shadow merges dropped unsettled at shutdown', {
                        count: this.deferredShadowMerges.length,
                    })
                    this.deferredShadowMerges = []
                }
                await this.shadowed('shutdown', () => this.personhog.shutdown())
            }
        }
    }
}
