import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'
import pLimit from 'p-limit'
import { Counter } from 'prom-client'

import { SEMANTIC_REFUSAL_METADATA_KEY, SEMANTIC_REFUSAL_OP_ID_REUSED } from '~/common/personhog/identity'
import { grpcErrorType } from '~/common/personhog/metrics'
import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogFencedError, PersonhogPropertiesSizeError } from '~/common/personhog/persons'
import { PersonMessage } from '~/common/persons/person-message'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult } from '~/common/utils/db/db'
import { logger } from '~/common/utils/logger'
import { NoRowsUpdatedError } from '~/common/utils/utils'
import { BatchWritingStoreFlushStats } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt } from '~/types'

import { MergeMode, PersonMergeCallFailedError } from './person-merge-types'
import { EventOps, applyEventPropertyUpdates, computeOpsScalarUpdates, foldOps, refineEventOps } from './person-update'
import { mergeOpIdFromRequest } from './person-uuid'
import { PersonhogPersonMemo } from './personhog-person-memo'
import { FlushResult, MergePersonsRequest, MergePersonsResult, PersonsStore } from './persons-store'
import { BatchBoundPersonsStore, PersonsStoreForBatch } from './persons-store-for-batch'

export const personhogStoreFlushCounter = new Counter({
    name: 'personhog_store_flush_ops_total',
    help: 'Lane write outcomes across the flush and merge-side paths, by outcome',
    labelNames: ['outcome'],
})

export const personhogStoreMergeCacheCounter = new Counter({
    name: 'personhog_store_merge_cache_total',
    help: 'What a merge did to the batch cache, its resolutions, and its lanes, by action',
    labelNames: ['action'],
})

export const personhogStoreShadowShedCounter = new Counter({
    name: 'personhog_store_shadow_shed_segments_total',
    help: 'Unwritten segments discarded at batch release in shadow mode, where a failed flush cannot fail the batch',
})

export const personhogStoreFlushErrorCounter = new Counter({
    name: 'personhog_store_flush_errors_total',
    help: 'Lane writes that failed without a classified outcome, by error class; the breakdown of flush_ops error',
    labelNames: ['error'],
})

export const personhogStorePrefetchFailedCounter = new Counter({
    name: 'personhog_store_prefetch_failed_total',
    help: 'Batch prefetches that failed, degrading the batch to resolving each distinct id on first touch',
})

export const personhogStoreUnsupportedFieldCounter = new Counter({
    name: 'personhog_store_unsupported_field_total',
    help: 'Direct updates refused because they carried a field this backend cannot write, by field',
    labelNames: ['field'],
})

export const personhogStoreMergeCallFailedCounter = new Counter({
    name: 'personhog_store_merge_call_failed_total',
    help: 'Merge calls that failed with no verdict, failing the batch to redeliver, by error class',
    labelNames: ['error'],
})

export const personhogStoreMergeOutcomeCounter = new Counter({
    name: 'personhog_store_merge_outcomes_total',
    help: 'Merge saga per-source outcomes observed by the ingestion client, by outcome',
    labelNames: ['outcome'],
})

export interface PersonhogPersonsStoreOptions {
    /** Bounds concurrent RPC fan-out; separate from the Postgres store's same-named pool option. */
    maxConcurrentUpdates: number
    /** Mirrors the Postgres store's option; both stores must be given the same value. */
    updateAllProperties: boolean
    /** The saga's per-source move guard for SYNC mode, which carries no limit of its own. */
    syncMergeMoveLimit: number
}

const DEFAULT_OPTIONS: PersonhogPersonsStoreOptions = {
    maxConcurrentUpdates: 10,
    updateAllProperties: false,
    syncMergeMoveLimit: 10_000,
}

const CALLER_TAG = 'ingestion/personhog-store'

/** A bounded label: gRPC faults carry their status code, everything else its constructor name. */
function flushErrorClass(error: unknown): string {
    if (error instanceof ConnectError) {
        return grpcErrorType(error)
    }
    const name = error instanceof Error ? error.constructor?.name : undefined
    return typeof name === 'string' && name.length > 0 && name.length <= 64 ? name : 'unknown'
}

/** SYNC uses the store's limit; other modes carry their own, validated at startup. */
function moveLimitFor(mergeMode: MergeMode, syncMergeMoveLimit: number): number {
    return mergeMode.type === 'SYNC' ? syncMergeMoveLimit : mergeMode.limit
}

/** The event name stamped on creation calls; per-event names are consumed at fold time. */
const CREATE_EVENT_NAME = '$create_person'

/** The event name stamped on direct diff updates, which carry no originating event. */
const DIRECT_UPDATE_EVENT_NAME = '$direct_update'

/** A person field the leader's update RPC cannot express; failing loudly beats silent divergence. */
export class PersonhogUnsupportedFieldError extends Error {
    constructor(fields: string[]) {
        super(`PersonhogPersonsStore cannot write person field(s): ${fields.join(', ')}`)
        this.name = 'PersonhogUnsupportedFieldError'
    }
}

/** Redirect re-entries one write pass spends chasing a merge chain before failing to redelivery. */
const REDIRECT_MAX_ATTEMPTS = 3

/** Rounds a flush waits on in-flight writers before failing rather than acking over unwritten ops. */
const FLUSH_MAX_WAIT_ROUNDS = 3
const FLUSH_WAIT_ROUND_MS = 1_000

/** A redirect failure that already incremented its own flush outcome. */
class CountedRedirectError extends Error {}

interface CapturedLane {
    personKey: string
    entry: OpsLaneEntry
    segments: number
}

interface OpsLaneEntry {
    teamId: number
    personId: string
    distinctId: string
    /** Folded ops; a new segment starts only when foldOps cannot represent the composition. */
    segments: EventOps[]
    /** Set while a flush is writing this entry's leading segments; folds arriving meanwhile start a new segment. */
    inFlight?: boolean
    /** Settles when the current direct write finishes, so a merge can await a write already on the wire. */
    directWriteSettled?: Promise<void>
    /** Resolves `directWriteSettled`; armed with it at claim time. */
    settleWrite?: () => void
    /** Set when a shadow-mode release abandoned this entry mid-write; the settle sheds it once unreferenced. */
    abandoned?: boolean
}

/**
 * The personhog person store: resolution and creation through the identity
 * service, person state through the leader's strong reads, and property
 * updates buffered as per-person lanes of folded ops. Unlike the Postgres
 * store it writes ops as stated; the leader resolves them authoritatively.
 */
export class PersonhogPersonsStore implements PersonsStore {
    readonly backend = 'personhog' as const

    private options: PersonhogPersonsStoreOptions
    /**
     * Folded ops, one entry per person, keyed by `${teamId}:${personId}` and
     * shared across batches so one writer owns each person.
     */
    private entries: Map<string, OpsLaneEntry> = new Map()
    /** Person keys each open batch references, for the release refcount. */
    private batchEntryKeys: Map<number, Set<string>> = new Map()
    /**
     * Batches with a prefetch still in flight; a response landing after its
     * batch released must not record for a batch nothing can release again.
     */
    private prefetchingBatches: Set<number> = new Set()
    private memo: PersonhogPersonMemo = new PersonhogPersonMemo(
        (personKey) => this.hasUnwrittenOps(personKey),
        (personKey, document) => this.projectPendingOps(personKey, document)
    )
    /** Serializes flush passes; see flush(). */
    private flushChain: Promise<void> = Promise.resolve()

    constructor(
        private repository: PersonHogPersonWriteRepository,
        options?: Partial<PersonhogPersonsStoreOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
        // A bad limit would fail every merge, or strand claimed lanes when
        // pLimit rejects it mid-flush; startup is where both fail usefully.
        if (!Number.isInteger(this.options.syncMergeMoveLimit) || this.options.syncMergeMoveLimit < 1) {
            throw new Error(
                `PERSONHOG_SYNC_MERGE_MOVE_LIMIT must be an integer >= 1, got ${this.options.syncMergeMoveLimit}`
            )
        }
        if (!Number.isInteger(this.options.maxConcurrentUpdates) || this.options.maxConcurrentUpdates < 1) {
            throw new Error(
                `PERSONHOG_STORE_MAX_CONCURRENT_UPDATES must be an integer >= 1, got ${this.options.maxConcurrentUpdates}`
            )
        }
    }

    forBatch(batchId: number): PersonsStoreForBatch {
        return new BatchBoundPersonsStore(this, batchId)
    }

    /** Resolves through identity and uses that person directly, saving the leader hop. */
    async fetchForChecking(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const cached = this.memo.lookup(teamId, distinctId)
        if (cached !== undefined) {
            return cached
        }
        const [resolved] = await this.repository.resolvePersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        return this.memo.record(teamId, distinctId, resolved?.person ?? null, batchId)
    }

    /** Identity resolves the distinct id, then the leader supplies the freshest document. */
    async fetchForUpdate(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const cached = this.memo.lookup(teamId, distinctId)
        if (cached !== undefined) {
            return cached
        }
        const [resolved] = await this.repository.resolvePersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        if (!resolved?.person) {
            return this.memo.record(teamId, distinctId, null, batchId)
        }
        // A null here means the person vanished between resolve and read
        // (merged or deleted mid-flight); record the resolution miss and
        // let the caller's create path re-resolve authoritatively.
        const person = await this.repository.fetchPersonById(teamId, resolved.person.id, CALLER_TAG)
        return this.memo.record(teamId, distinctId, person, batchId)
    }

    async createPerson(
        createdAt: DateTime,
        properties: Properties,
        _propertiesLastUpdatedAt: PropertiesLastUpdatedAt,
        _propertiesLastOperation: PropertiesLastOperation,
        teamId: number,
        _isUserId: number | null,
        isIdentified: boolean,
        _uuid: string,
        primaryDistinctId: { distinctId: string; version?: number },
        extraDistinctIds: { distinctId: string; version?: number }[] | undefined,
        _tx: PersonRepositoryTransaction | undefined,
        batchId: number
    ): Promise<CreatePersonResult> {
        const createResult = await this.repository.getOrCreatePersonByDistinctId(
            {
                teamId,
                distinctId: primaryDistinctId.distinctId,
                extraDistinctIds: extraDistinctIds?.map(({ distinctId }) => distinctId),
                eventName: CREATE_EVENT_NAME,
                setProperties: properties,
                createdAtMs: createdAt.toMillis(),
                isIdentified,
            },
            CALLER_TAG
        )
        const { created } = createResult
        let { person } = createResult
        if (!created) {
            // Identity's found-branch document lags the leader, so pay a
            // leader read for the baseline. A null means the person was
            // deleted or merged away mid-call; the caller keeps identity's
            // answer and the redirect heals any ops folded onto it.
            const leaderDoc = await this.repository.fetchPersonById(teamId, person.id, CALLER_TAG)
            if (leaderDoc === null) {
                this.memo.dropBaseline(`${teamId}:${person.id}`)
                return { success: true, person: this.memo.snapshot(person), messages: [], created }
            }
            person = leaderDoc
        }
        const personKey = `${teamId}:${person.id}`
        this.memo.recordResolution(batchId, `${teamId}:${primaryDistinctId.distinctId}`, personKey)
        // Extras are never memoized: the service can leave a conflicting
        // extra mapped to its existing person, so they resolve on first touch.
        this.memo.offerBaseline(personKey, person)
        // The identity service publishes its own downstream messages on creation.
        return { success: true, person: this.memo.snapshot(person), messages: [], created }
    }

    async applyEventOps(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string,
        batchId: number
    ): Promise<[InternalPerson, PersonMessage[]]> {
        // The denylist gates property writes only: a denied op still
        // advances identity and last-seen, matching the Postgres store.
        if (ops.denied && ops.isIdentified === undefined && ops.lastSeenAtMs === undefined) {
            return [person, []]
        }
        // A merge can destroy the person between this resolve and the
        // lane's flush; the tombstone redirect then carries the ops to the
        // survivor, which is where a racing write lands under Postgres too.
        const target = await this.personNow(person, distinctId, batchId)
        return this.foldEventOps(target, ops, distinctId, batchId)
    }

    /**
     * The person this distinct id belongs to now: a merge may have
     * destroyed the copy the caller resolved earlier. The answer always
     * leaves through the memo, never straight out of a read.
     */
    private async personNow(person: InternalPerson, distinctId: string, batchId: number): Promise<InternalPerson> {
        const resolved = this.memo.lookup(person.team_id, distinctId)
        if (resolved) {
            return resolved
        }
        // An edge naming somebody other than the caller's person is the
        // newer truth; one read settles it. A wrong fold heals at flush
        // through the tombstone redirect either way.
        const edge = this.memo.resolutionOf(`${person.team_id}:${distinctId}`)
        if (edge == null || edge === `${person.team_id}:${person.id}`) {
            return person
        }
        await this.fetchForUpdate(person.team_id, distinctId, batchId)
        return this.memo.lookup(person.team_id, distinctId) ?? person
    }

    private foldEventOps(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string,
        batchId: number
    ): [InternalPerson, PersonMessage[]] {
        // The view this event produces for its caller, matching what Postgres would
        // apply. The leader's application at flush is the authoritative one.
        const refined = refineEventOps(ops, person.properties ?? {}, this.options.updateAllProperties, false)
        const [projected] = applyEventPropertyUpdates(refined, person)
        const scalarUpdates = computeOpsScalarUpdates(ops, projected)
        Object.assign(projected, scalarUpdates)

        const personKey = `${person.team_id}:${person.id}`
        this.referenceEntry(batchId, personKey)
        // Seeded only while the lane is empty: an existing lane's caller
        // holds a store-composed view, and seeding from it would replay
        // ops it already contains.
        if (!this.hasUnwrittenOps(personKey)) {
            this.memo.offerBaseline(personKey, person)
        }
        const existing = this.entries.get(personKey)
        if (!existing) {
            this.entries.set(personKey, {
                teamId: person.team_id,
                personId: person.id,
                distinctId,
                segments: [ops],
            })
        } else {
            const last = existing.segments.length - 1
            const lastSegment = existing.segments[last]
            // A flush snapshots the leading segments and truncates exactly
            // that many, so folding into one already on the wire would change
            // the payload underneath it or lose this event.
            const folded = lastSegment === undefined || existing.inFlight ? null : foldOps(lastSegment, ops)
            if (folded === null) {
                existing.segments.push(ops)
            } else {
                existing.segments[last] = folded
            }
        }
        // The ops live in the lane; the memo composes the view on read, so
        // every id of this person sees the change pre-flush.
        this.memo.recordResolution(batchId, `${person.team_id}:${distinctId}`, personKey)
        return [this.memo.viewOfPerson(personKey) ?? this.memo.snapshot(projected), []]
    }

    /**
     * Runs the identity service's merge saga and folds its outcome into
     * the batch view: ids naming a destroyed person resolve to the
     * survivor. A call with no verdict drops the team's resolutions
     * instead, since which persons died is unknowable.
     */
    async mergePersons(request: MergePersonsRequest, batchId: number): Promise<MergePersonsResult> {
        const fresh = await this.resolveForDrain(
            request.teamId,
            [request.targetDistinctId, ...request.sources.map((source) => source.distinctId)],
            batchId
        )
        // A lane keyed on a stale memo belief is not drained; its ops land
        // after the merge through the tombstone redirect.
        const personKeys = [...new Set(fresh.values())]
        // Claims arm their settle promise, so a writer already on the wire
        // is visible here even before it reaches its concurrency slot;
        // waiting lets the drain capture its lane instead of skipping it.
        const inFlightWrites = personKeys
            .map((personKey) => this.entries.get(personKey)?.directWriteSettled)
            .filter((settled): settled is Promise<void> => settled !== undefined)
        if (inFlightWrites.length > 0) {
            await Promise.all(inFlightWrites)
        }
        // Best-effort: a lane the drain cannot write right now (bounced on
        // a leader fence, or claimed by a redirect) lands after the merge
        // through the tombstone redirect instead of inside the fold.
        await this.writeLanesBeforeMerge(personKeys)
        const result = await this.runMerge(request, batchId)
        return { ...result, survivor: this.memo.snapshot(result.survivor) }
    }

    /**
     * One batched identity resolve of a merge's named ids, answering
     * `distinctId -> personKey`; results record into the memo.
     */
    private async resolveForDrain(
        teamId: number,
        distinctIds: string[],
        batchId: number
    ): Promise<Map<string, string>> {
        const resolvedKeys = new Map<string, string>()
        let resolved
        try {
            resolved = await this.repository.resolvePersonsByDistinctIds(
                distinctIds.map((distinctId) => ({ teamId, distinctId })),
                CALLER_TAG
            )
        } catch (error) {
            // Wrapped: unwrapped it reaches the merge service's catch-all,
            // which would ack the event with the merge lost.
            personhogStoreMergeCacheCounter.inc({ action: 'drain_resolve_failed' })
            throw new PersonMergeCallFailedError(
                `personhog merge drain resolve failed: ${error instanceof Error ? error.message : String(error)}`,
                error
            )
        }
        for (const entry of resolved) {
            if (entry.person) {
                resolvedKeys.set(entry.distinctId, `${teamId}:${entry.person.id}`)
                this.memo.record(entry.teamId, entry.distinctId, entry.person, batchId)
            }
        }
        return resolvedKeys
    }

    /**
     * Writes every affected lane before the merge goes out, so the saga
     * folds people whose buffered changes already landed. Best-effort: a
     * lane it cannot write lands after the merge through the redirect.
     */
    private async writeLanesBeforeMerge(personKeys: string[]): Promise<void> {
        const captured: CapturedLane[] = []
        // Every named person's lane, whichever distinct id opened it;
        // Postgres reaches a pending update through any of a person's ids.
        for (const personKey of personKeys) {
            const entry = this.entries.get(personKey)
            if (!entry || entry.segments.length === 0) {
                continue
            }
            // A redirect owns the lane; its ops land on the survivor after
            // the merge rather than inside the fold.
            if (entry.inFlight) {
                personhogStoreMergeCacheCounter.inc({ action: 'premerge_lane_in_flight' })
                continue
            }
            this.claimForWrite(entry)
            captured.push({ personKey, entry, segments: entry.segments.length })
        }
        if (captured.length === 0) {
            return
        }
        const limit = pLimit(this.options.maxConcurrentUpdates)
        const outcomes = await Promise.allSettled(
            captured.map(({ personKey, entry, segments }) => limit(() => this.writeEntry(personKey, entry, segments)))
        )
        for (const outcome of outcomes) {
            if (outcome.status !== 'rejected') {
                continue
            }
            const error = outcome.reason
            // A lifecycle op holds the person, often this request's own from
            // an interrupted delivery. Calling the saga settles either case;
            // the lane's ops stay and land through the redirect.
            if (error instanceof PersonhogFencedError) {
                personhogStoreMergeCacheCounter.inc({ action: 'premerge_lane_fenced' })
                continue
            }
            // The typed wrapper is what makes the merge service fail the
            // batch; a generic catch would ack and drop the merge.
            throw new PersonMergeCallFailedError(
                `personhog pre-merge write failed: ${error instanceof Error ? error.message : String(error)}`,
                error
            )
        }
    }

    private async runMerge(request: MergePersonsRequest, batchId: number): Promise<MergePersonsResult> {
        const singleSource = request.sources.length === 1
        let result
        try {
            result = await this.repository.mergePersons(
                {
                    teamId: request.teamId,
                    targetDistinctId: request.targetDistinctId,
                    sources: request.sources,
                    eventSet: request.eventOps.set,
                    eventSetOnce: request.eventOps.setOnce,
                    // The uuidv5 derivation scopes client-supplied uuids per
                    // team, and the source list keeps a fold and its
                    // fallback merges on separate keys.
                    opId: mergeOpIdFromRequest(
                        request.teamId,
                        request.eventUuid,
                        request.sources.map((source) => source.distinctId),
                        moveLimitFor(request.mergeMode, this.options.syncMergeMoveLimit)
                    ),
                    allowIdentifiedSources: request.allowIdentifiedSources,
                    moveLimit: moveLimitFor(request.mergeMode, this.options.syncMergeMoveLimit),
                    // The saga refuses a negative created_at and pre-1970
                    // events exist; floored here where the constraint lives.
                    createdAtMs: Math.max(0, request.createdAtMs),
                    // The raw event uuid, which the op id carries only as a
                    // one-way derivation; the saga stamps it on a birth.
                    creatorEventUuid: request.eventUuid,
                },
                CALLER_TAG
            )
        } catch (error) {
            // A verdict, not an unknowable failure: redelivery meets the
            // same validation forever, so it propagates raw to be acked
            // loudly rather than wedging the partition.
            if (error instanceof ConnectError && error.code === Code.InvalidArgument) {
                personhogStoreMergeCallFailedCounter.inc({ error: 'InvalidArgumentSettled' })
                throw error
            }
            // Deterministic and pre-durable, so it propagates raw. Keyed on
            // the reason slug: a semantic refusal from a later saga step
            // must still take the invalidation below.
            if (
                error instanceof ConnectError &&
                error.metadata.get(SEMANTIC_REFUSAL_METADATA_KEY) === SEMANTIC_REFUSAL_OP_ID_REUSED
            ) {
                personhogStoreMergeCallFailedCounter.inc({ error: 'OpIdReusedSettled' })
                throw error
            }
            // No verdict, so an ack could lose the merge. Only the call is
            // wrapped, so a post-verdict bug surfaces as itself. Any edges
            // the failed saga flipped heal through the tombstone redirect.
            personhogStoreMergeCallFailedCounter.inc({
                error:
                    error instanceof ConnectError
                        ? `connect_${Code[error.code] ?? error.code}`
                        : error instanceof Error
                          ? error.constructor.name
                          : 'unknown',
            })
            throw new PersonMergeCallFailedError(
                `personhog merge call failed with no verdict: ${error instanceof Error ? error.message : String(error)}`,
                error
            )
        }
        for (const source of result.results) {
            personhogStoreMergeOutcomeCounter.inc({ outcome: source.outcome })
        }
        const touched = result.results
            .filter((source) => ['merged', 'attached', 'noop_same_person'].includes(source.outcome))
            .map((source) => source.sourceDistinctId)
        const merged = result.results.filter((source) => source.outcome === 'merged')
        this.reconcileMergedPersons(
            request.teamId,
            merged.flatMap((source) =>
                source.sourcePersonId != null ? [`${request.teamId}:${source.sourcePersonId}`] : []
            ),
            result.survivor ? `${request.teamId}:${result.survivor.id}` : undefined,
            batchId
        )
        // A fold that skipped any source aborts, after reconcile keeps what
        // merged: acking skipped sources is a durability decision the
        // all-or-nothing Postgres fold never makes, so each gets its own
        // sequential decision on redelivery.
        if (!singleSource) {
            const overLimit = result.results.some((source) => source.outcome === 'skipped_move_limit')
            const conflicted = result.results.some((source) => source.outcome === 'skipped_conflict')
            const refused = result.results.some((source) => source.outcome === 'skipped_refused')
            // An error verdict with no merged source can only be an abort,
            // because completion implies at least one source folded.
            const errored = merged.length === 0 && result.results.some((source) => source.outcome === 'error')
            if (overLimit || conflicted || refused || errored) {
                personhogStoreMergeCacheCounter.inc({ action: 'fold_skip_abort' })
                if (result.survivor) {
                    // The saga's partial folds moved the leader despite the
                    // abort; the next reader re-reads.
                    this.memo.dropBaseline(`${request.teamId}:${result.survivor.id}`)
                }
                return {
                    survivor: null,
                    results: [],
                    foldAborted: overLimit ? 'limit' : conflicted ? 'conflict' : refused ? 'refused' : 'error',
                }
            }
        }
        if (result.survivor) {
            // Serves the batch's later reads of the touched ids without a
            // re-resolve; a replayed verdict's older document loses.
            this.memo.record(request.teamId, request.targetDistinctId, result.survivor, batchId)
            for (const distinctId of touched) {
                this.memo.record(request.teamId, distinctId, result.survivor, batchId)
            }
        }
        return {
            survivor: result.survivor,
            results: result.results,
        }
    }

    /** An entry outlives its segments, so existence alone does not prove unwritten ops. */
    private hasUnwrittenOps(personKey: string): boolean {
        return (this.entries.get(personKey)?.segments.length ?? 0) > 0
    }

    /**
     * A service document with the lane's unsent ops replayed over it. A
     * segment leaves the lane before its write goes out, so the ops
     * replayed here are exactly the ones the leader has not seen.
     */
    private projectPendingOps(personKey: string, document: InternalPerson): InternalPerson {
        const segments = this.entries.get(personKey)?.segments
        if (segments === undefined || segments.length === 0) {
            return this.memo.snapshot(document)
        }
        return this.projectOver(document, segments)
    }

    /** The leader enforces the size ceiling at admission; there is nothing to measure here. */
    personPropertiesSize(_personId: string, _teamId: number): Promise<number> {
        return Promise.resolve(0)
    }

    getFlushStats(): BatchWritingStoreFlushStats {
        return {
            dirtyEntryCount: [...this.entries.values()].filter((entry) => entry.segments.length > 0).length,
            referencedBatchCount: this.batchEntryKeys.size,
            cacheEntryCount: this.memo.baselineCount,
        }
    }

    /**
     * A direct diff update mapped onto the leader's folded-update RPC;
     * fields with no RPC counterpart fail loudly rather than dropping. This
     * path buffers nothing; a race with a merge bounces on the leader's
     * fence and the batch redelivers.
     */
    async updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        _distinctId: string,
        _batchId: number,
        forceUpdate?: boolean,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        const unsupported = Object.keys(otherUpdates).filter((key) => key !== 'is_identified' && key !== 'last_seen_at')
        if (unsupported.length > 0) {
            // One count per field keeps the label bounded by the schema
            // rather than its power set.
            for (const field of unsupported) {
                personhogStoreUnsupportedFieldCounter.labels({ field }).inc()
            }
            throw new PersonhogUnsupportedFieldError(unsupported)
        }
        const { person: updated, updated: applied } = await this.repository.updatePersonProperties(
            {
                teamId: person.team_id,
                personId: person.id,
                eventName: DIRECT_UPDATE_EVENT_NAME,
                setProperties: propertiesToSet,
                setOnceProperties: {},
                unsetProperties: propertiesToUnset,
                isIdentified: otherUpdates.is_identified === true ? true : undefined,
                lastSeenAtMs: otherUpdates.last_seen_at?.toMillis(),
                forceUpdate: forceUpdate ?? false,
            },
            CALLER_TAG
        )
        const personKey = `${person.team_id}:${person.id}`
        if (!updated) {
            // A null document with the write applied means the leader moved
            // past whatever we held; drop the baseline so the next reader
            // re-reads. Without an applied write it is a genuine no-op.
            if (applied) {
                this.memo.dropBaseline(personKey)
            }
            return [person, [], false]
        }
        // This path bypasses the lane, so buffered ops replay on top; the
        // edge is recorded so the baseline releases with the batch.
        this.memo.recordResolution(_batchId, `${person.team_id}:${_distinctId}`, personKey)
        this.memo.offerBaseline(personKey, updated)
        // No ClickHouse message: the leader's changelog is the person feed.
        return [updated, [], false]
    }

    /**
     * One identity resolve for the batch's distinct ids, then leader state
     * reads for the hits: the same two-step the update fetch does singly,
     * done once so per-event processing hits the memo. Best-effort.
     */
    async prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void> {
        const seen = new Set<string>()
        const unresolved = teamDistinctIds.filter((entry) => {
            const key = `${entry.teamId}:${entry.distinctId}:${entry.batchId}`
            if (seen.has(key)) {
                return false
            }
            seen.add(key)
            return this.memo.lookup(entry.teamId, entry.distinctId) === undefined
        })
        if (unresolved.length === 0) {
            return
        }
        for (const entry of unresolved) {
            this.prefetchingBatches.add(entry.batchId)
        }
        try {
            const resolved = await this.repository.resolvePersonsByDistinctIds(
                unresolved.map((entry) => ({ teamId: entry.teamId, distinctId: entry.distinctId })),
                CALLER_TAG
            )
            const limit = pLimit(this.options.maxConcurrentUpdates)
            await Promise.all(
                resolved.map((entry, i) =>
                    limit(async () => {
                        const { batchId } = unresolved[i]
                        // Re-checked before recording: the batch can release
                        // while the response is in flight, and recording for
                        // a released batch recreates its key set so nothing
                        // ever releases it again.
                        if (!this.prefetchingBatches.has(batchId)) {
                            return
                        }
                        if (!entry.person) {
                            this.memo.record(entry.teamId, entry.distinctId, null, batchId)
                            return
                        }
                        const person = await this.repository.fetchPersonById(entry.teamId, entry.person.id, CALLER_TAG)
                        if (!this.prefetchingBatches.has(batchId)) {
                            return
                        }
                        // Fill-only: this response raced everything the batch
                        // did since the request went out, so it may supply a
                        // document but must not move a standing edge.
                        this.memo.record(entry.teamId, entry.distinctId, person, batchId, { fillOnly: true })
                    })
                )
            )
        } catch (error) {
            // Counted because the degradation is silent: every id just
            // resolves on first touch and it reads as latency.
            personhogStorePrefetchFailedCounter.inc()
            logger.warn('personhog prefetch failed; resolution falls back to first touch', { error })
        }
    }

    /**
     * Writes the batch's folded lanes to the leader, one call per segment;
     * nothing publishes, because the leader's changelog is the person feed.
     * A missing person redirects to whatever its distinct id resolves to
     * now; a person genuinely gone and a size rejection are counted and
     * dropped since neither can succeed on retry; anything else fails the
     * flush. Passes serialize.
     */
    async flush(): Promise<FlushResult[]> {
        const run = this.flushChain.then(() => this.flushPass())
        this.flushChain = run.then(
            () => undefined,
            () => undefined
        )
        return run
    }

    private async flushPass(): Promise<FlushResult[]> {
        // Success here is what lets the batch ack, so the pass must not
        // return while any lane still holds unwritten segments: a lane
        // another writer has claimed is waited out and rewritten, or the
        // pass fails and the batch redelivers.
        for (let round = 0; ; round++) {
            const pass = { deferrals: 0 }
            await this.writeEligibleLanes(pass)
            if (pass.deferrals === 0) {
                // No FlushResults: the leader's changelog is the ClickHouse
                // person feed, so a flush publishes nothing — writing the
                // segments is the whole job.
                return []
            }
            if (round >= FLUSH_MAX_WAIT_ROUNDS) {
                personhogStoreFlushCounter.inc({ outcome: 'parked_exhausted' })
                throw new Error(
                    `flush cannot complete: ${pass.deferrals} lanes deferred behind writes that did not settle`
                )
            }
            // Wait for the in-flight writers to settle before retrying,
            // bounded so a wedged writer exhausts the rounds instead of
            // hanging the flush past the consumer's poll budget.
            const settles = [...this.entries.values()]
                .filter((entry) => entry.segments.length > 0)
                .map((entry) => entry.directWriteSettled)
                .filter((settled): settled is Promise<void> => settled !== undefined)
            let timer: NodeJS.Timeout | undefined
            try {
                await Promise.race([
                    Promise.allSettled(settles),
                    new Promise<void>((resolve) => {
                        timer = setTimeout(resolve, FLUSH_WAIT_ROUND_MS)
                    }),
                ])
            } finally {
                clearTimeout(timer)
            }
        }
    }

    private async writeEligibleLanes(pass: { deferrals: number }): Promise<void> {
        // No await in this block: the snapshot is atomic, and a failure
        // leaves each entry as it was with no claim to strand.
        const captured: CapturedLane[] = []
        for (const [personKey, entry] of this.entries) {
            if (entry.segments.length === 0) {
                continue
            }
            // Another writer holds the lane; returning now would ack over
            // its unwritten ops, so the round loop waits it out.
            if (entry.inFlight) {
                pass.deferrals += 1
                continue
            }
            this.claimForWrite(entry)
            captured.push({ personKey, entry, segments: entry.segments.length })
        }
        const limit = pLimit(this.options.maxConcurrentUpdates)
        const outcomes = await Promise.allSettled(
            captured.map(({ personKey, entry, segments }) => limit(() => this.writeEntry(personKey, entry, segments)))
        )
        const failed = outcomes.find((outcome): outcome is PromiseRejectedResult => outcome.status === 'rejected')
        if (failed) {
            throw failed.reason
        }
    }

    /**
     * Clears the in-flight mark and retires an entry with nothing left.
     * Runs on every exit from a write; a mark left set would strand the ops.
     */
    private releaseWritten(personKey: string, entry: OpsLaneEntry): void {
        entry.inFlight = false
        entry.settleWrite?.()
        entry.settleWrite = undefined
        entry.directWriteSettled = undefined
        if (entry.segments.length > 0) {
            // An abandoned entry's failed write would persist as ownerless
            // retry work; the settle is the last hand that holds it.
            if (entry.abandoned && !this.entryHeldByAnyBatch(personKey) && this.entries.get(personKey) === entry) {
                personhogStoreShadowShedCounter.inc(entry.segments.length)
                entry.segments.length = 0
                this.retireEntry(personKey)
            }
            return
        }
        // Identity-guarded: a stale finalizer settling after the entry was
        // retired and recreated must not retire the new entry's ops.
        if (!this.entryHeldByAnyBatch(personKey) && this.entries.get(personKey) === entry) {
            this.retireEntry(personKey)
        }
    }

    private async writeEntry(personKey: string, entry: OpsLaneEntry, segments: number): Promise<void> {
        try {
            // What this pass still owes; array length is no substitute,
            // since folds arriving mid-redirect inflate it with segments
            // this pass never attempted.
            const progress = { remaining: segments }
            // Terminates: every iteration writes the remainder, drops a
            // unit, or throws; a fresh tombstone re-enters the redirect,
            // bounded like the Postgres retry loop so a lineage merging
            // faster than we can chase fails to redelivery.
            let viaRedirect = false
            let redirects = 0
            while (progress.remaining > 0) {
                try {
                    if (viaRedirect) {
                        await this.redirectToSurvivor(entry, progress)
                        personhogStoreFlushCounter.inc({ outcome: 'redirected' })
                        break
                    }
                    await this.writeSegments(entry, entry.personId, progress)
                    personhogStoreFlushCounter.inc({ outcome: 'success' })
                    break
                } catch (error) {
                    if (error instanceof NoRowsUpdatedError && redirects < REDIRECT_MAX_ATTEMPTS) {
                        // The person was merged or deleted since the fold.
                        // The direct write is over; the lane is
                        // redirect-owned from here.
                        redirects += 1
                        entry.settleWrite?.()
                        entry.settleWrite = undefined
                        entry.directWriteSettled = undefined
                        viaRedirect = true
                        continue
                    }
                    if (error instanceof PersonhogPropertiesSizeError) {
                        // The rejected segment can never succeed, so it goes
                        // and the loop writes the remainder, unlike Postgres
                        // where one oversized row aborts the batch statement.
                        // The leader's customer warning is throttled per
                        // team, so the log attributes the individual discard.
                        personhogStoreFlushCounter.inc({ outcome: 'size_violation' })
                        logger.warn('🤔', 'leader refused a write on properties size; the ops are discarded', {
                            team_id: entry.teamId,
                            person_id: entry.personId,
                            distinct_id: entry.distinctId,
                        })
                        entry.segments.shift()
                        progress.remaining -= 1
                        continue
                    }
                    // A redirect failure already recorded its own outcome;
                    // recounting would file it twice.
                    if (!(error instanceof CountedRedirectError)) {
                        personhogStoreFlushCounter.inc({ outcome: 'error' })
                        personhogStoreFlushErrorCounter.inc({ error: flushErrorClass(error) })
                    }
                    if (error instanceof PersonhogFencedError) {
                        // An expected coordination outcome: the holder
                        // settles or the ghost fence heals, and redelivery flows.
                        logger.warn('flush bounced on a lifecycle fence; the batch redelivers', {
                            teamId: entry.teamId,
                            personId: entry.personId,
                            fencingOpId: error.fencingOpId,
                        })
                    } else {
                        logger.error('Failed to flush folded update to personhog', {
                            teamId: entry.teamId,
                            personId: entry.personId,
                            error,
                        })
                    }
                    // The unwritten segments stay in the entry for the next pass.
                    throw error
                }
            }
        } finally {
            this.releaseWritten(personKey, entry)
        }
    }

    /**
     * Marks a lane as this writer's and arms the promise a merge awaits.
     * Armed at claim time, not write start, so a merge cannot miss a lane
     * yet to reach its concurrency slot.
     */
    private claimForWrite(entry: OpsLaneEntry): void {
        entry.inFlight = true
        entry.settleWrite = undefined
        entry.directWriteSettled = new Promise((resolve) => {
            entry.settleWrite = resolve
        })
    }

    /**
     * A service document with a lane's unsent ops applied on top, built
     * from the same refine-and-apply pair the Postgres backend writes
     * through; the events were already counted at fold.
     */
    private projectOver(person: InternalPerson, segments: EventOps[]): InternalPerson {
        let projected = person
        for (const ops of segments) {
            const refined = refineEventOps(ops, projected.properties ?? {}, this.options.updateAllProperties, false)
            const [applied] = applyEventPropertyUpdates(refined, projected)
            projected = { ...applied, ...computeOpsScalarUpdates(ops, applied) }
        }
        return projected
    }

    /**
     * Writes a lane's leading segments, removing each as it lands so a
     * partial failure discards nothing unattempted.
     */
    private async writeSegments(entry: OpsLaneEntry, personId: string, progress: { remaining: number }): Promise<void> {
        const count = Math.min(progress.remaining, entry.segments.length)
        for (let written = 0; written < count; written++) {
            // The segment stays in the lane while on the wire and leaves it
            // in the same synchronous step that installs the answer, so no
            // reader sees the op counted twice or not at all.
            const ops = entry.segments[0]
            const { person: answer } = await this.repository.updatePersonProperties(
                {
                    teamId: entry.teamId,
                    personId,
                    eventName: ops.eventName,
                    setProperties: ops.set,
                    setOnceProperties: ops.setOnce,
                    unsetProperties: ops.unset,
                    isIdentified: ops.isIdentified,
                    lastSeenAtMs: ops.lastSeenAtMs,
                    forceUpdate: ops.shouldForceUpdate,
                },
                CALLER_TAG
            )
            entry.segments.shift()
            progress.remaining -= 1
            // Only where the lane owns the person: a redirect writes to a
            // survivor whose baseline answers for another lane, and the
            // redirect drops that baseline itself.
            if (personId === entry.personId) {
                const personKey = `${entry.teamId}:${personId}`
                if (answer !== null) {
                    this.memo.offerBaseline(personKey, answer)
                } else {
                    // The call returned without throwing, so the write
                    // applied and the leader moved past what we held; drop
                    // the baseline so the next reader re-reads.
                    this.memo.dropBaseline(personKey)
                }
            }
        }
    }

    /**
     * Re-resolves a lane's distinct id after its person vanished and
     * writes the segments to whoever owns the id now, matching the
     * Postgres store's merged-away recovery. One resolve is enough: the
     * saga repoints mappings in Postgres before the leader ever answers a
     * tombstone, so a fresh owner is already visible, and no owner means
     * the person was genuinely deleted, where redelivery recreates
     * through the normal pipeline.
     */
    private async redirectToSurvivor(entry: OpsLaneEntry, progress: { remaining: number }): Promise<void> {
        const [resolved] = await this.repository.resolvePersonsByDistinctIds(
            [{ teamId: entry.teamId, distinctId: entry.distinctId }],
            CALLER_TAG
        )
        const survivorId = resolved?.person?.id
        if (survivorId === undefined || survivorId === entry.personId) {
            // Release the edge so the redelivered events re-resolve rather
            // than folding onto the corpse again.
            this.memo.releaseResolution(`${entry.teamId}:${entry.distinctId}`)
            this.memo.dropBaseline(`${entry.teamId}:${entry.personId}`)
            personhogStoreFlushCounter.inc({ outcome: 'redirect_gone' })
            throw new CountedRedirectError(
                `person ${entry.personId} in team ${entry.teamId} vanished and ${entry.distinctId} resolves to ` +
                    `${survivorId === undefined ? 'nobody' : 'the same person'}; failing the flush to redeliver`
            )
        }
        // The resolve proved where the id belongs, so heal the memo before
        // the write — the same repoint the Postgres cache performs — and
        // later events fold onto the survivor whatever the write's fate.
        this.memo.repointResolution(`${entry.teamId}:${entry.distinctId}`, `${entry.teamId}:${survivorId}`)
        this.memo.dropBaseline(`${entry.teamId}:${entry.personId}`)
        // Ops travel as they stand, deletions included, matching Postgres.
        await this.writeSegments(entry, survivorId, progress)
        // The survivor's baseline cannot know about these ops.
        this.memo.dropBaseline(`${entry.teamId}:${survivorId}`)
    }

    /**
     * Reconciles the batch view against the persons a merge destroyed,
     * clearing each person and every distinct id that mapped to it. Ops
     * still buffered for a destroyed person are kept: their next write
     * meets the tombstone and redirects to the survivor.
     */
    private reconcileMergedPersons(
        teamId: number,
        destroyedPersonKeys: string[],
        survivorKey: string | undefined,
        batchId: number
    ): void {
        // Only server-named person ids reconcile: those persons are gone
        // with their ids and baselines. Anything the memo merely believes
        // heals through the tombstone redirect when a write proves it.
        const authoritative = new Set<string>(destroyedPersonKeys)
        // The survivor is never a destroyed source of its own merge; a memo
        // edge that says otherwise is stale and claims nothing.
        if (survivorKey !== undefined) {
            authoritative.delete(survivorKey)
        }
        if (authoritative.size === 0) {
            return
        }
        // A lane holding ops for a destroyed person is left to write: its
        // flush meets the tombstone and redirects to the survivor.
        // Discarding here would drop writes Postgres carries across.
        let stranded = 0
        for (const [personKey, entry] of this.entries) {
            if (!authoritative.has(personKey) || entry.segments.length === 0) {
                continue
            }
            stranded += entry.segments.length
        }
        if (stranded > 0) {
            personhogStoreMergeCacheCounter.inc({ action: 'lane_redirected_after_merge' })
        }
        let cleared = 0
        // Collected first: the loop repoints and releases edges in the same
        // map it walks.
        const resolutionEdges = this.memo.resolutionEdges()
        for (const [key, personKey] of resolutionEdges) {
            if (personKey === null) {
                continue
            }
            if (authoritative.has(personKey)) {
                if (survivorKey !== undefined) {
                    // Every id of a destroyed person belongs to the survivor,
                    // including ones this request never named; leaving them
                    // unresolved would send a resuming fold back to the dead
                    // person.
                    this.memo.recordResolution(batchId, key, survivorKey)
                } else {
                    this.memo.releaseResolution(key)
                }
                cleared++
            }
        }
        personhogStoreMergeCacheCounter.inc({ action: 'resolution_cleared' }, cleared)
        for (const personKey of authoritative) {
            this.memo.deletePerson(personKey)
        }
        if (stranded > 0) {
            logger.info('merge destroyed a person still holding folded ops; the flush redirects them', {
                team_id: teamId,
                segments: stranded,
            })
        }
    }

    /**
     * Frees a completed batch's memos and drops its references to shared
     * entries; an entry still holding unwritten ops when its last
     * reference goes is deferred rather than evicted.
     */
    releaseBatch(batchId: number): void {
        // Any prefetch still on the wire answers into nothing from here on.
        this.prefetchingBatches.delete(batchId)
        // Entries first: the distinct-key release below must see the entry
        // map in its final state to judge which baselines lanes keep alive.
        const keys = this.batchEntryKeys.get(batchId)
        this.batchEntryKeys.delete(batchId)
        for (const personKey of keys ?? []) {
            if (this.entryHeldByAnyBatch(personKey)) {
                continue
            }
            const entry = this.entries.get(personKey)
            if (entry && entry.segments.length > 0) {
                // The entry stays until its write drains it.
                continue
            }
            this.retireEntry(personKey)
        }
        this.memo.releaseBatch(batchId)
    }

    /**
     * Releases a batch, discarding the unwritten segments the batch alone
     * was keeping: the shadow valve. A shadow flush failure cannot fail
     * the batch, so keeping these lanes would grow without bound under a
     * sustained personhog outage; what is shed is counted.
     */
    abandonBatch(batchId: number): void {
        this.prefetchingBatches.delete(batchId)
        const keys = this.batchEntryKeys.get(batchId)
        this.batchEntryKeys.delete(batchId)
        for (const personKey of keys ?? []) {
            if (this.entryHeldByAnyBatch(personKey)) {
                continue
            }
            const entry = this.entries.get(personKey)
            if (entry?.inFlight) {
                // The write owns the lane; the flag hands the shed to the
                // write's settle instead of zeroing segments under it.
                entry.abandoned = true
                continue
            }
            if (entry && entry.segments.length > 0) {
                personhogStoreShadowShedCounter.inc(entry.segments.length)
                entry.segments.length = 0
            }
            this.retireEntry(personKey)
        }
        this.memo.releaseBatch(batchId)
    }

    /**
     * Drops a drained entry and, with it, the baseline it was keeping
     * alive when no resolution still names that person.
     */
    private retireEntry(personKey: string): void {
        this.entries.delete(personKey)
        this.memo.evictBaseline(personKey)
    }

    /** Records that this batch is folding into a person's shared entry. */
    private referenceEntry(batchId: number, personKey: string): void {
        let keys = this.batchEntryKeys.get(batchId)
        if (!keys) {
            keys = new Set()
            this.batchEntryKeys.set(batchId, keys)
        }
        keys.add(personKey)
    }

    /**
     * Whether any open batch still names this person's entry. A scan, not
     * a counter: batches number in the handful and a counter can drift.
     */
    private entryHeldByAnyBatch(personKey: string): boolean {
        for (const keys of this.batchEntryKeys.values()) {
            if (keys.has(personKey)) {
                return true
            }
        }
        return false
    }

    shutdown(): Promise<void> {
        // Lanes still holding ops at shutdown mean the drain order is wrong
        // somewhere; the data is redelivery-safe, the bug must be loud.
        const unwritten = [...this.entries.values()].filter((entry) => entry.segments.length > 0).length
        if (unwritten > 0) {
            return Promise.reject(
                new Error(`PersonhogPersonsStore shut down with ${unwritten} lanes holding unwritten ops`)
            )
        }
        return Promise.resolve()
    }
}
