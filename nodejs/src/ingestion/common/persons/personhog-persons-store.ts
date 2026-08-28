import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'
import pLimit from 'p-limit'
import { Counter, Gauge } from 'prom-client'

import { GRPC_DEFAULT_ATTEMPTS } from '~/common/personhog/grpc-retry'
import { SEMANTIC_REFUSAL_METADATA_KEY, SEMANTIC_REFUSAL_OP_ID_REUSED } from '~/common/personhog/identity'
import { grpcErrorType } from '~/common/personhog/metrics'
import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogFencedError, PersonhogPropertiesSizeError } from '~/common/personhog/persons'
import { PersonMessage } from '~/common/persons/person-message'
import { PersonClaimedByLifecycleOpError } from '~/common/persons/repositories/person-repository'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult } from '~/common/utils/db/db'
import { logger } from '~/common/utils/logger'
import { defaultRetryConfig } from '~/common/utils/retries'
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

export const personhogStoreStaleReadCounter = new Counter({
    name: 'personhog_store_stale_read_total',
    help: 'Update-class reads answered below a standing version floor; retried re-reads, exhausted fails the batch',
    labelNames: ['outcome'],
})

export const personhogStoreDeathStampCounter = new Counter({
    name: 'personhog_store_death_stamps_total',
    help: 'Destroyed-person marks stamped, by the signal that proved the death; a spike on one site attributes it',
    labelNames: ['site'],
})

export const personhogStoreDestroyedMarksGauge = new Gauge({
    name: 'personhog_store_destroyed_marks',
    help: 'Destroyed-person marks the memo holds; retained for the verdict-replay window, so the population tracks merge volume over the last ~25h',
})

export const personhogStoreFenceCounter = new Counter({
    name: 'personhog_store_fence_waits_total',
    help: 'Fence encounters across folds and merge-side writes, by outcome',
    labelNames: ['outcome'],
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

export const personhogStorePersonNowExhaustedCounter = new Counter({
    name: 'personhog_store_person_now_exhausted_total',
    help: 'Folds that gave up re-reading a distinct id because merges kept overtaking the read',
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
    /**
     * Bounds concurrent RPC fan-out. Its own knob because the Postgres
     * store's identically named option guards a connection pool this store
     * does not hold.
     */
    maxConcurrentUpdates: number
    /**
     * Whether every property change triggers a person update, matching the
     * Postgres store's option of the same name. Both stores must be given
     * the same value or their views diverge by construction.
     */
    updateAllProperties: boolean
    /**
     * The saga's per-source move guard for SYNC mode, which carries no limit
     * of its own. A source over it comes back skipped_move_limit and the
     * merge-mode policy decides the event's fate.
     */
    syncMergeMoveLimit: number
    /**
     * The ceiling on any wait for a local fence. A fence is held by a
     * sibling merge call in this process for that call's whole duration, so
     * this must exceed the merge deadline times its transport-retry
     * attempts, or the leak alarm fires on legitimately slow merges and
     * fails their co-batch work. The caller derives it from those knobs;
     * see the wiring in ingestion-api-server. It deliberately does not
     * cover the compound worst case (conflict-salted retries that are each
     * transport-degraded, several minutes): expiry there is a safe
     * redelivery, and a ceiling that large would collide with the
     * consumer's poll interval instead.
     */
    fenceWaitMs: number
}

/**
 * The fence-wait ceiling for a given merge deadline: the deadline times
 * the transport-retry attempts the repository actually makes, plus a
 * margin for the other work a fence is held across — the in-flight
 * write settle, one concurrency wave of pre-merge lane writes with any
 * tombstone-redirect resolves they pay, and the survivor refresh, each
 * bounded by the much shorter point-read deadline. (The merge's own
 * identity resolve runs before the fences install and is not held
 * work.) The margin covers the typical case plus any one contributor
 * fully transport-degraded, not all of them compounded. Deliberately
 * not covered: that compound, more fenced lanes than the write
 * concurrency admits in one wave, a lane with many segments each fully
 * transport-degraded, and the conflict-salted retry compound; each
 * expires into a safe redelivery, where a ceiling large enough for
 * them would collide with the consumer's poll interval instead.
 */
export function derivedFenceWaitMs(mergeTimeoutMs: number): number {
    return mergeTimeoutMs * GRPC_DEFAULT_ATTEMPTS + 15_000
}

/**
 * The document a merge hands its caller: the refreshed read, unless the
 * response survivor is strictly newer. A read served by a deposed leader
 * inside its detection window can answer below the merge's own commit;
 * the memo's floor already refuses that install, and this guards the
 * returned copy, which a fold plan serves to every later event in its
 * run.
 */
function newerSurvivor(response: InternalPerson, refreshed: InternalPerson): InternalPerson {
    if (
        typeof response.version === 'number' &&
        typeof refreshed.version === 'number' &&
        refreshed.version < response.version
    ) {
        // A strong read below the merge's own commit is the deposed-leader
        // detection window showing itself; the count is the one trace an
        // operator gets, since the floor's install refusals are silent.
        personhogStoreMergeCacheCounter.inc({ action: 'refresh_below_response' })
        return response
    }
    return refreshed
}

const DEFAULT_OPTIONS: PersonhogPersonsStoreOptions = {
    maxConcurrentUpdates: 10,
    updateAllProperties: false,
    syncMergeMoveLimit: 10_000,
    fenceWaitMs: derivedFenceWaitMs(35_000),
}

const CALLER_TAG = 'ingestion/personhog-store'

/**
 * A bounded label for an unclassified flush failure. gRPC faults all arrive
 * as one class, so they carry their status code; everything else uses its
 * constructor name, which is a small fixed set here.
 */
function flushErrorClass(error: unknown): string {
    if (error instanceof ConnectError) {
        return grpcErrorType(error)
    }
    const name = error instanceof Error ? error.constructor?.name : undefined
    return typeof name === 'string' && name.length > 0 && name.length <= 64 ? name : 'unknown'
}

/** Every move limit the saga accepts is an integer of at least 1. */
function assertMoveLimit(source: string, limit: number): void {
    if (!Number.isInteger(limit) || limit < 1) {
        throw new Error(`${source} must be an integer >= 1, got ${limit}`)
    }
}

/**
 * SYNC carries no limit of its own, so it uses the store's. Other modes carry
 * a configured one that `determineMergeMode` already validated at startup.
 */
function moveLimitFor(mergeMode: MergeMode, syncMergeMoveLimit: number): number {
    return mergeMode.type === 'SYNC' ? syncMergeMoveLimit : mergeMode.limit
}

/** The event name stamped on creation calls; per-event names are consumed at fold time. */
const CREATE_EVENT_NAME = '$create_person'

/** The event name stamped on direct diff updates, which carry no originating event. */
const DIRECT_UPDATE_EVENT_NAME = '$direct_update'

/**
 * A wait ran out the deadline it was given while the person was still fenced.
 * Callers share one deadline across a chain of waits, so this is not
 * necessarily one fence outlasting the fence-wait ceiling. Fails the batch rather than
 * folding against a person the merge is still deciding.
 */
export class PersonhogFenceTimeoutError extends Error {
    constructor(personKey: string, waitedMs: number) {
        super(`merge fence on ${personKey} still held when the wait's deadline expired, after ${waitedMs}ms`)
        this.name = 'PersonhogFenceTimeoutError'
    }
}

/**
 * A person field this backend cannot express. The leader's update RPC carries
 * a fixed set, so anything outside it fails loudly rather than being dropped
 * on the floor where the two backends would silently diverge.
 */
export class PersonhogUnsupportedFieldError extends Error {
    constructor(fields: string[]) {
        super(`PersonhogPersonsStore cannot write person field(s): ${fields.join(', ')}`)
        this.name = 'PersonhogUnsupportedFieldError'
    }
}

/**
 * Bounds the re-resolve loop so a lineage merging faster than the flush can
 * drain still terminates. Exhausting it throws rather than dropping.
 */
const REDIRECT_MAX_ATTEMPTS = 5

/**
 * How many reads a fold spends on a distinct id whose edge names a person the
 * caller does not hold. One read settles the answer into the memo; a further
 * one is only needed when a merge landed during that read and made it
 * unrecordable. Two consecutive overtakes on one id is already pathological,
 * so the third gives up rather than reading against a moving memo forever.
 */
const PERSON_NOW_MAX_READS = 3

/**
 * How many times an update-class fetch re-reads a person whose answers
 * keep arriving below the standing floor. The leader that set the floor
 * serves at or past it on a fresh read, so one retry normally clears it;
 * exhaustion means reads are being served from before a version the
 * leader provably passed, and failing the batch beats classifying
 * against them.
 */
const FLOOR_READ_MAX_ATTEMPTS = 3

/**
 * Pause between re-resolves while identity still answers with a person the
 * leader has already lost. Identity lags the leader, so a stale answer and a
 * deleted person look alike and the first reply cannot be trusted.
 */
const REDIRECT_REFRESH_INTERVAL_MS = 100

/**
 * How many wait-and-redirect rounds a flush spends on lanes parked behind
 * merges before failing the pass rather than acking over unwritten ops.
 */
const FLUSH_MAX_MERGE_WAIT_ROUNDS = 3

type RedirectOutcome = 'written' | 'gone' | 'size_violation'

/** A redirect failure that already incremented its own flush outcome. */
class CountedRedirectError extends Error {}

/** A lane claimed for one write pass, with the segment count that pass owns. */
interface CapturedLane {
    personKey: string
    entry: OpsLaneEntry
    segments: number
}

/** A source a merge destroyed. */
interface DestroyedSource {
    /** Absent on a server that does not report the id. */
    personKey: string | undefined
    distinctKey: string
    /** The memo's pre-resolve belief for the id, when it had one. */
    beliefKey?: string
}

interface OpsLaneEntry {
    teamId: number
    personId: string
    distinctId: string
    /**
     * Folded ops in arrival order. Almost always one; a new segment starts
     * only when foldOps cannot represent the composition.
     */
    segments: EventOps[]
    /**
     * Whether any folded event updates the person against its baseline
     * baseline. A lane that never sets this holds filtered-only noise, which
     * flush suppresses as the Postgres store does.
     */
    triggersUpdate: boolean
    /**
     * Set while a flush is writing this entry's leading segments. Folds
     * arriving meanwhile start a new segment.
     */
    inFlight?: boolean
    /**
     * Settles when the current direct write finishes, before any redirect. A
     * merge awaits this after fencing so a write already on the wire lands
     * before the saga applies the merge event's own $set. Redirects are
     * excluded because they wait on the merge's fence.
     */
    directWriteSettled?: Promise<void>
    /** Resolves `directWriteSettled`; armed with it at claim time. */
    settleWrite?: () => void
    /**
     * Set when a shadow-mode release abandoned this entry while its write
     * was in flight. A successful write drains it normally; a failed one
     * would otherwise leave an entry with segments and no owner that no
     * later abandon can reach, so the settle sheds it instead once nothing
     * references it. A live batch referencing the entry needs no clearing:
     * the settle's own reference check is what protects its ops.
     */
    abandoned?: boolean
}

/**
 * The personhog person store: resolution and creation through the identity
 * service, person state through the leader's strong reads, and property
 * updates as raw op folds the leader refines under its per-person lock.
 *
 * Where the Postgres store refines ops against a fetched snapshot before
 * writing, this one writes them as stated, so it needs no version-race
 * machinery. Fetches memoize per batch; folded ops accumulate per person as
 * a lane of segments, and a flush writes one call per segment. Ops fold into
 * the open segment where they can, so a lane splits only where the leader's
 * apply order makes a single call answer differently from two.
 *
 * Person uuids derive from team_id:distinct_id on the identity service, so
 * the uuid argument to createPerson is advisory.
 */
export class PersonhogPersonsStore implements PersonsStore {
    readonly backend = 'personhog' as const

    private options: PersonhogPersonsStoreOptions
    /**
     * Folded ops, one entry per person, keyed by `${teamId}:${personId}` and
     * shared across batches. One entry means one writer, so two batches
     * holding the same person cannot let an older value land last.
     */
    private entries: Map<string, OpsLaneEntry> = new Map()
    /** Person keys each open batch references, for the release refcount. */
    private batchEntryKeys: Map<number, Set<string>> = new Map()
    /**
     * Batches with a prefetch still in flight. A prefetch is issued without
     * being awaited, so its response can arrive after the batch released,
     * and a resolution recorded then is held by a batch that can never
     * release it again.
     */
    private prefetchingBatches: Set<number> = new Set()
    /**
     * Resolutions, baselines, and their per-batch liveness. The callbacks
     * supply the lane facts it needs: whether a person has unwritten ops,
     * which keeps its baseline alive, and how to replay those ops over a
     * baseline to get the view a read answers with.
     */
    private memo: PersonhogPersonMemo = new PersonhogPersonMemo(
        (personKey) => this.hasUnwrittenOps(personKey),
        (personKey, document) => this.projectPendingOps(personKey, document),
        (personKey) => this.entries.get(personKey)?.inFlight === true
    )
    /**
     * Every merge currently holding each person. A fold onto one waits for
     * those merges to settle, so ops cannot accumulate behind a sent request.
     * Set-valued because a person can be one merge's source and another's
     * target, so it stays fenced until its last holder releases.
     */
    private fences: Map<string, Set<Promise<void>>> = new Map()
    /**
     * Redirects in flight, keyed by the person being written TO. The lane
     * itself sits under its vanished person's key, so a merge fencing the
     * survivor cannot find it through the entry map and needs this registry
     * to wait it out. Set-valued: one pass can redirect several lanes to one
     * survivor.
     */
    private redirectsInFlight: Map<string, Set<Promise<void>>> = new Map()
    /** Serializes flush passes; see flush(). */
    private flushChain: Promise<void> = Promise.resolve()

    constructor(
        private repository: PersonHogPersonWriteRepository,
        options?: Partial<PersonhogPersonsStoreOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
        // A limit below 1 draws INVALID_ARGUMENT from the saga, and a
        // non-integer throws a RangeError inside BigInt() when the request is
        // built. Either fails every merge in the deployment, so fail startup.
        assertMoveLimit('PERSONHOG_SYNC_MERGE_MOVE_LIMIT', this.options.syncMergeMoveLimit)
        // pLimit throws on a value below 1 or a non-integer, and it is built
        // after lanes have been claimed for a write. Failing there leaves
        // them marked in flight with nothing left to clear the mark, so every
        // later pass defers them and the flush exhausts its rounds. Startup
        // is the only place this can fail usefully.
        if (!Number.isInteger(this.options.maxConcurrentUpdates) || this.options.maxConcurrentUpdates < 1) {
            throw new Error(
                `PERSONHOG_STORE_MAX_CONCURRENT_UPDATES must be an integer >= 1, got ${this.options.maxConcurrentUpdates}`
            )
        }
    }

    forBatch(batchId: number): PersonsStoreForBatch {
        return new BatchBoundPersonsStore(this, batchId)
    }

    /**
     * Resolves through identity and uses that person directly: writer-applied
     * state is within this read class's eventual contract, and it saves the
     * leader hop.
     */
    async fetchForChecking(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const cached = this.memo.lookup(teamId, distinctId, 'checking')
        if (cached !== undefined) {
            return cached
        }
        const read = this.memo.beginRead(teamId, batchId, [`${teamId}:${distinctId}`])
        const [resolved] = await this.repository.resolvePersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        const answered = resolved?.person ? `${teamId}:${resolved.person.id}` : undefined
        if (read.moved(`${teamId}:${distinctId}`, answered)) {
            // A merge rewrote the memo mid-flight, so this response may name
            // a person it destroyed. The caller gets the answer; the memo
            // keeps the merge's.
            return this.memo.snapshot(resolved?.person ?? null)
        }
        return this.memo.record(teamId, distinctId, resolved?.person ?? null, batchId, { readClass: 'checking' })
    }

    /**
     * Splits resolution from state: identity resolves the distinct id, then
     * the leader supplies the person. The baseline this feeds enriches the
     * batch's events, so the baseline has to be the leader's.
     */
    async fetchForUpdate(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const cached = this.memo.lookup(teamId, distinctId, 'update')
        if (cached !== undefined) {
            return cached
        }
        const read = this.memo.beginRead(teamId, batchId, [`${teamId}:${distinctId}`])
        const [resolved] = await this.repository.resolvePersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        if (!resolved?.person) {
            if (read.moved(`${teamId}:${distinctId}`)) {
                return null
            }
            return this.memo.record(teamId, distinctId, null, batchId, { readClass: 'update' })
        }
        // A null here means the person vanished between resolve and read
        // (merged or deleted mid-flight); record the resolution miss and
        // let the caller's create path re-resolve authoritatively.
        //
        // A document below the standing floor is provably stale: the memo
        // would refuse to install it, but handing it to the caller would
        // let the fold classify ops against it and suppress a genuine
        // change as no-change — the same returned-copy asymmetry the merge
        // path guards with its version comparison. Re-read bounded; on
        // exhaustion fail the batch rather than classify against it.
        let person: InternalPerson | null
        for (let attempt = 1; ; attempt++) {
            person = await this.repository.fetchPersonById(teamId, resolved.person.id, CALLER_TAG)
            if (person === null || !this.memo.refusesBelowFloor(`${teamId}:${resolved.person.id}`, person)) {
                break
            }
            personhogStoreStaleReadCounter.inc({
                outcome: attempt === FLOOR_READ_MAX_ATTEMPTS ? 'exhausted' : 'retried',
            })
            if (attempt === FLOOR_READ_MAX_ATTEMPTS) {
                throw new Error(
                    `person ${resolved.person.id} in team ${teamId} kept reading below the version floor after ` +
                        `${FLOOR_READ_MAX_ATTEMPTS} attempts; failing rather than classifying against a stale document`
                )
            }
            // Back-to-back re-reads would all land inside the same deposed
            // leader's detection window; the pause is what gives the loop a
            // chance to outlive it. The caller's generic retry spreads the
            // exhaustion throw further, but that is its own policy, not
            // something this loop may lean on.
            await new Promise((resolve) => setTimeout(resolve, 50 * attempt))
        }
        if (read.moved(`${teamId}:${distinctId}`, `${teamId}:${resolved.person.id}`)) {
            // A merge spoke for this id mid-flight; hand back the read but
            // leave the memo with the merge's answer.
            return this.memo.snapshot(person)
        }
        return this.memo.record(teamId, distinctId, person, batchId, { readClass: 'update' })
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
        // Every id this call will map, because it records them all and a
        // merge speaking for any one of them makes the whole answer older
        // than the merge's.
        const writtenKeys = [
            primaryDistinctId.distinctId,
            ...(extraDistinctIds ?? []).map((extra) => extra.distinctId),
        ].map((id) => `${teamId}:${id}`)
        const read = this.memo.beginRead(teamId, batchId, writtenKeys)
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
        // Whether this person's state came through the leader, which decides
        // the provenance its baseline is installed under. A created person
        // counts: creation is leader-durable, so the document is the leader's.
        let leaderBacked = created
        if (!created) {
            // Identity's document lags the leader, and it becomes the
            // baseline the caller's ops fold against, where a stale value can
            // make a genuinely new $set classify as no-change. So this branch
            // pays the same leader read the update fetch does.
            const leaderDoc = await this.repository.fetchPersonById(teamId, person.id, CALLER_TAG)
            if (leaderDoc === null) {
                // The leader answers null only for a person deleted or
                // merged away — a merge on another pod leaves no local
                // stamp for the moved check below to see, and this read is
                // the one death signal this pod gets. Stamped like the
                // redirect's gone arm: the marks keep the dead document out
                // of the memo (the caller still folds against it, which the
                // flush's destroyed-person rescue converts into a write the
                // tombstone redirect carries to the survivor), and the id
                // bumps refuse any read already on the wire that would
                // reinstall the dead answer. The caller gets the identity
                // answer; the next event's resolve reads the survivor once
                // identity catches up.
                personhogStoreDeathStampCounter.inc({ site: 'create_leader_null' })
                this.memo.markDestroyed(`${teamId}:${person.id}`)
                for (const key of writtenKeys) {
                    this.memo.bumpId(key)
                }
                return { success: true, person: this.memo.snapshot(person), messages: [], created }
            }
            person = leaderDoc
            leaderBacked = true
        }
        // The person this call answered with travels too: a merge can destroy
        // it without naming any of these ids, which is the same sibling case
        // the read paths guard against.
        const answered = `${teamId}:${person.id}`
        if (writtenKeys.some((key) => read.moved(key, answered))) {
            // A merge spoke for one of these ids while this call was in
            // flight; the response may describe a person the merge
            // destroyed. The caller still gets it — installing it is what
            // must not happen.
            return { success: true, person: this.memo.snapshot(person), messages: [], created }
        }
        const personKey = `${teamId}:${person.id}`
        this.memo.recordResolution(batchId, `${teamId}:${primaryDistinctId.distinctId}`, personKey)
        // Extras are never memoized, on either branch: `created` speaks only
        // for the primary. The service's create leaves a live conflicting
        // extra mapped to its existing person while still reporting the
        // primary's creation, so an edge recorded here could name a person
        // the service never mapped that id to. Extras resolve on first
        // touch instead.
        this.memo.offerBaseline(personKey, person, leaderBacked ? 'leader-read' : 'identity-read')
        // The identity service publishes its own downstream messages on
        // the creation branch, so none are surfaced here.
        return { success: true, person: this.memo.snapshot(person), messages: [], created }
    }

    applyEventOps(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string,
        batchId: number
    ): Promise<[InternalPerson, PersonMessage[]]> {
        // The denylist gates property writes only: a denied op still
        // advances identity and last-seen, matching the Postgres store
        // and the leader's own refinement. Denied ops carrying no
        // scalars have nothing to contribute at all.
        if (ops.denied && ops.isIdentified === undefined && ops.lastSeenAtMs === undefined) {
            return Promise.resolve([person, []])
        }

        // The caller resolved its person before this call, and a merge that
        // ran and released since then leaves no fence to wait on, so the
        // memo is consulted first either way. Folding onto a person a merge
        // destroyed would repoint the id back at it and hand every later
        // event in the batch a pre-merge baseline.
        return this.foldOntoCurrentPerson(person, ops, distinctId, batchId)
    }

    private async foldOntoCurrentPerson(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string,
        batchId: number
    ): Promise<[InternalPerson, PersonMessage[]]> {
        // Resolving the id can read, so this yields even when nothing is
        // fenced. What has to stay indivisible is the pair below: the held
        // check and the fold run with no await between them, so a merge
        // cannot take the person after the check says it is free.
        const target = await this.personNow(person, distinctId, batchId)
        // Folding onto a person a merge is holding would put operations
        // behind a request already on the wire, where they would land after
        // the merge instead of taking part in it.
        if (this.isHeldByOther(`${target.team_id}:${target.id}`)) {
            return this.foldAfterFences(target, ops, distinctId, batchId)
        }
        return this.foldEventOps(target, ops, distinctId, batchId)
    }

    /**
     * Waits a held person out and folds onto whoever owns the id afterwards.
     * The person that comes back is often not the one waited on, since a
     * merge repoints the id to its survivor before releasing and that
     * survivor may be held by another merge. Folding onto a held person would
     * land the ops inside that merge's request, so the wait repeats until the
     * id settles on someone free.
     */
    private async foldAfterFences(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string,
        batchId: number
    ): Promise<[InternalPerson, PersonMessage[]]> {
        // One deadline for every hop, so a fast-merging lineage delays this
        // event without outlasting the poll interval.
        const deadline = Date.now() + this.options.fenceWaitMs
        let target = person
        for (;;) {
            await this.awaitFences(`${target.team_id}:${target.id}`, undefined, deadline)
            const settled = await this.personNow(target, distinctId, batchId)
            if (!this.isHeldByOther(`${settled.team_id}:${settled.id}`)) {
                return this.foldEventOps(settled, ops, distinctId, batchId)
            }
            // `awaitFences` gives up on the deadline, but only while a fence
            // is up when it runs. A fence released just before it and
            // reinstalled just after leaves it returning immediately every
            // pass, and resolving the id now reads, so without a check here
            // the loop spends unbounded reads never reaching a free person.
            if (Date.now() >= deadline) {
                personhogStoreFenceCounter.inc({ outcome: 'fold_deadline_exceeded' })
                throw new PersonhogFenceTimeoutError(
                    `${settled.team_id}:${settled.id}`,
                    Date.now() - (deadline - this.options.fenceWaitMs)
                )
            }
            target = settled
        }
    }

    /**
     * Whether any merge but the caller's own holds this person. Avoids
     * building the holder list, because every fold asks and almost every
     * answer is no.
     */
    private isHeldByOther(personKey: string, ownFence?: Promise<void>): boolean {
        const held = this.fences.get(personKey)
        if (held === undefined) {
            return false
        }
        if (ownFence === undefined) {
            return held.size > 0
        }
        for (const fence of held) {
            if (fence !== ownFence) {
                return true
            }
        }
        return false
    }

    /** The merges holding this person, excluding the caller's own. */
    private heldBy(personKey: string, ownFence?: Promise<void>): Promise<void>[] {
        const held = this.fences.get(personKey)
        if (held === undefined) {
            return []
        }
        return [...held].filter((fence) => fence !== ownFence)
    }

    /**
     * Waits out every merge holding the person, including fences installed
     * behind them: a release only proves the earlier merges settled.
     *
     * Whether a caller waits at all depends on `ownFence`. A caller holding
     * no fence waits, leaving when the person comes free or the deadline
     * runs out. A caller holding one never waits; the refusal below says why.
     *
     * Callers pass one deadline for a whole chain rather than a budget per
     * round, because rounds nest inside repointing hops and redirect
     * retries, and per-round budgets would multiply.
     */
    private async awaitFences(personKey: string, ownFence: Promise<void> | undefined, deadline: number): Promise<void> {
        const startedAt = Date.now()
        for (;;) {
            const held = this.heldBy(personKey, ownFence)
            if (held.length === 0) {
                return
            }
            if (ownFence !== undefined) {
                // A fence holder never waits on somebody else's fence.
                // Two merges whose person sets cross would each block on a
                // fence only the other can release, and neither releases
                // until its own call returns. Refusing unwinds this merge and
                // drops its fences, so the contention clears and the step's
                // retry runs once that merge has settled.
                personhogStoreFlushCounter.inc({ outcome: 'redirect_fenced_during_merge' })
                throw new CountedRedirectError(
                    `person ${personKey} is held by another merge; failing rather than waiting under our own fence`
                )
            }
            if (Date.now() >= deadline) {
                // The ceiling covers a merge's single-call transport bound
                // (see fenceWaitMs), so getting here means a fence outlived
                // its call — a leak — or the compound worst case of
                // conflict-salted retries each transport-degraded, where
                // failing to redelivery is the deliberate line. The elapsed
                // time is measured, not reported as the ceiling, since the
                // deadline is shared across waits.
                personhogStoreFenceCounter.inc({ outcome: 'wait_deadline_exceeded' })
                throw new PersonhogFenceTimeoutError(personKey, Date.now() - startedAt)
            }
            await this.awaitFence(
                personKey,
                Promise.all(held).then(() => undefined),
                deadline
            )
        }
    }

    /**
     * The person this distinct id belongs to now. The caller resolved its own
     * copy earlier, so a merge that has since destroyed that person leaves it
     * naming somebody who no longer exists; folding onto that would repoint
     * the distinct id back at the dead person and hand every later event a
     * pre-merge view.
     *
     * A successful merge repoints every id it destroyed before releasing the
     * fence, so the memo is authoritative and a miss on both facts means the
     * id was left alone. A failed merge releases the team's resolutions
     * instead, so a miss there falls back to the caller's person; if that
     * person did die, the write meets the tombstone and the redirect reaches
     * the survivor.
     *
     * The answer always leaves through the memo, never straight out of a
     * read. A read is the one await on this path, and a merge completing
     * inside it would otherwise hand back a person it has already destroyed,
     * which the fold would then name as the id's owner.
     */
    private async personNow(person: InternalPerson, distinctId: string, batchId: number): Promise<InternalPerson> {
        const distinctKey = `${person.team_id}:${distinctId}`
        let reads = 0
        // Every read is followed by a memo consult, so the bound counts
        // reads rather than passes: ending on a read would throw away the
        // answer it just settled.
        for (;;) {
            const resolved = this.memo.lookup(person.team_id, distinctId, 'checking')
            if (resolved) {
                return resolved
            }
            // Identity and document are separate facts, and a miss above
            // answers both at once. An edge naming somebody other than the
            // caller's person is the newer truth, and the caller's person is
            // the one a merge left behind, so the document has to be read
            // rather than folded onto. Dropping a baseline is only safe
            // because of this.
            const edge = this.memo.resolutionOf(distinctKey)
            if (edge == null || edge === `${person.team_id}:${person.id}`) {
                return person
            }
            if (reads === PERSON_NOW_MAX_READS) {
                // Reached only where the memo names somebody other than the
                // caller's person, so folding onto the caller's would repoint
                // this id off the survivor and onto a person a merge left
                // behind, and every later event in the batch would compose on
                // top of it. Failing redelivers the batch, which costs a
                // round trip and keeps the ops.
                personhogStorePersonNowExhaustedCounter.inc()
                throw new Error(
                    `distinct id ${distinctId} in team ${person.team_id} belongs to another person and ` +
                        `could not be read in ${PERSON_NOW_MAX_READS} attempts; failing rather than folding onto ${person.id}`
                )
            }
            reads += 1
            // The read settles into the memo, so the answer this loop
            // returns always comes from the memo rather than from a value
            // that raced it. A merge landing during the read makes
            // `fetchForUpdate` decline to record, and the next pass reads
            // the state that merge left instead of folding onto a person it
            // may have just destroyed.
            await this.fetchForUpdate(person.team_id, distinctId, batchId)
        }
    }

    private async awaitFence(personKey: string, fence: Promise<void>, expiresAt: number): Promise<void> {
        let timer: NodeJS.Timeout | undefined
        const expired = new Promise<'timeout'>((resolve) => {
            // Whatever is left of the caller's deadline, since this runs
            // inside loops that would otherwise multiply a fresh one.
            timer = setTimeout(() => resolve('timeout'), Math.max(0, expiresAt - Date.now()))
        })
        try {
            const outcome = await Promise.race([fence.then(() => 'released' as const), expired])
            personhogStoreFenceCounter.inc({ outcome })
        } finally {
            clearTimeout(timer)
        }
    }

    /**
     * Holds a set of persons for the duration of a merge. Callers release
     * from a `finally`, since a fence left standing makes every later fold
     * for those persons wait out the full ceiling.
     */
    private fencePersons(personKeys: string[]): { release: () => void; fence: Promise<void> } {
        let release: () => void = () => {}
        const fence = new Promise<void>((resolve) => {
            release = resolve
        })
        for (const personKey of personKeys) {
            const held = this.fences.get(personKey)
            if (held === undefined) {
                this.fences.set(personKey, new Set([fence]))
                continue
            }
            held.add(fence)
        }
        return {
            fence,
            release: () => {
                for (const personKey of personKeys) {
                    const held = this.fences.get(personKey)
                    if (held === undefined) {
                        continue
                    }
                    held.delete(fence)
                    if (held.size === 0) {
                        this.fences.delete(personKey)
                    }
                }
                release()
            },
        }
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
        // An update means a non-filtered change against the baseline or a
        // moved scalar. Filtered-only noise leaves this false and is
        // suppressed at flush.
        const triggersUpdate =
            (refined.hasChanges && refined.hasNonFilteredChanges) || Object.keys(scalarUpdates).length > 0

        const personKey = `${person.team_id}:${person.id}`
        this.referenceEntry(batchId, personKey)
        // A first touch arrives with the person its caller read and no
        // baseline recorded, and the lane about to hold ops is worthless
        // without a document to replay them over.
        //
        // Only while the lane is empty, because only then is the caller's
        // person known to be free of unsent ops. Once a lane exists the
        // caller is holding a view this store composed, and seeding from it
        // would replay ops it already contains: an event that both sets and
        // unsets a key resolves the other way on a document that has already
        // taken it. With no baseline the view is genuinely unknown, which is
        // what a lookup miss says, and the next read settles it.
        if (!this.hasUnwrittenOps(personKey)) {
            this.memo.offerBaseline(personKey, person, 'identity-read')
        }
        const existing = this.entries.get(personKey)
        if (!existing) {
            this.entries.set(personKey, {
                teamId: person.team_id,
                personId: person.id,
                distinctId,
                segments: [ops],
                triggersUpdate,
            })
        } else {
            existing.triggersUpdate = existing.triggersUpdate || triggersUpdate
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
        // Nothing is installed for the person. The ops are in the lane now,
        // and the memo works the view out from the baseline and the lane
        // whenever somebody reads, so every distinct id resolving to this
        // person sees the change pre-flush and the next event composes.
        this.memo.recordResolution(batchId, `${person.team_id}:${distinctId}`, personKey)
        return [this.memo.viewOfPerson(personKey) ?? this.memo.snapshot(projected), []]
    }

    /**
     * Runs the identity service's merge saga, which owns execution end to end
     * (fencing, folding, repointing, tombstoning), and folds its outcome into
     * the batch view: ids naming a destroyed person resolve to the survivor.
     * A call that fails without a verdict drops the team's resolutions
     * instead, since which persons died is then unknowable.
     */
    async mergePersons(request: MergePersonsRequest, batchId: number): Promise<MergePersonsResult> {
        // The memo's view of the named ids, captured before the fresh
        // resolve moves any edges: a fence has to cover what this pod
        // BELIEVES as well as what identity says, or a lane keyed on a
        // stale belief goes unguarded.
        const memoOf = (distinctId: string) => this.memo.resolutionOf(`${request.teamId}:${distinctId}`)
        const memoSourceKeys = request.sources.map((source) => memoOf(source.distinctId))
        const memoTargetKey = memoOf(request.targetDistinctId)
        // Resolve every named id in one batched call, the way the saga will:
        // a source person this pod has never touched still needs its fence,
        // or a first-touch fold lands mid-merge and races the request.
        const fresh = await this.resolveForFence(
            request.teamId,
            [request.targetDistinctId, ...request.sources.map((source) => source.distinctId)],
            batchId
        )
        // A source may name two persons, the memo's belief and identity's
        // answer, and both are fenced.
        const sourceKeys = request.sources.flatMap((source, index) => [
            ...new Set(
                [fresh.get(source.distinctId), memoSourceKeys[index]].filter(
                    (personKey): personKey is string => personKey != null
                )
            ),
        ])
        const targetKey = fresh.get(request.targetDistinctId) ?? memoTargetKey
        const personKeys = [
            ...new Set([
                ...(targetKey != null ? [targetKey] : []),
                ...(memoTargetKey != null ? [memoTargetKey] : []),
                ...sourceKeys,
            ]),
        ]
        // Held for the whole call, including reconciliation, so a fold that
        // was waiting resumes against the merged world rather than into a
        // request that has already gone.
        let releaseFence: (() => void) | undefined
        // Ownership is tested against this promise's identity, never against
        // the key set: a person can be held by several merges, so "the key is
        // mine" would let a write proceed under another merge's fence too.
        let ownFence: Promise<void> | undefined
        try {
            const fenced = this.fencePersons(personKeys)
            releaseFence = fenced.release
            ownFence = fenced.fence
            // A write claimed before the fence went up may already be on the
            // wire, and landing after the fold would overwrite what the merge
            // decided. Claims arm their settle promise, so a writer is
            // visible here even before it reaches its concurrency slot.
            const inFlightWrites = [
                ...personKeys.map((personKey) => this.entries.get(personKey)?.directWriteSettled),
                ...personKeys.flatMap((personKey) => [...(this.redirectsInFlight.get(personKey) ?? [])]),
            ].filter((settled): settled is Promise<void> => settled !== undefined)
            if (inFlightWrites.length > 0) {
                await Promise.all(inFlightWrites)
            }
            // Every op id this request could be running under. Derived before
            // the writes, which may bounce off a fence this same saga holds
            // from an earlier parked delivery; only the op id tells that from
            // somebody else's. Conflict suffixes are included because a
            // parked delivery may have used one.
            const sagaOpIds = this.sagaOpIdCandidates(request)
            // Written behind the fence, so the saga folds people whose
            // buffered changes already landed with their own precedence, and
            // the lanes are empty when it applies the merge event's own.
            await this.writeLanesBeforeMerge(personKeys, sagaOpIds, request, ownFence)
            const result = await this.runMerge(
                request,
                batchId,
                new Map(
                    request.sources.flatMap((source, index) =>
                        memoSourceKeys[index] != null
                            ? [[source.distinctId, memoSourceKeys[index]] as [string, string]]
                            : []
                    )
                )
            )
            return { ...result, survivor: this.memo.snapshot(result.survivor) }
        } finally {
            releaseFence?.()
        }
    }

    /**
     * One batched identity resolve of a merge's named ids, answering
     * `distinctId -> personKey`. Results are recorded as checking-class
     * reads, so reconcile's memo fallback sees them too.
     */
    private async resolveForFence(
        teamId: number,
        distinctIds: string[],
        batchId: number
    ): Promise<Map<string, string>> {
        const resolvedKeys = new Map<string, string>()
        const read = this.memo.beginRead(
            teamId,
            batchId,
            distinctIds.map((distinctId) => `${teamId}:${distinctId}`)
        )
        let resolved
        try {
            resolved = await this.repository.resolvePersonsByDistinctIds(
                distinctIds.map((distinctId) => ({ teamId, distinctId })),
                CALLER_TAG
            )
        } catch (error) {
            // This answer decides which persons are held and written before
            // the fold. Falling back to the memo would leave any person it
            // has not seen unheld and unwritten, and the saga folds it
            // anyway, so its buffered ops land after the fold unordered.
            //
            // Wrapped, because an unwrapped error reaches the merge service's
            // catch-all, which logs and acks the event with the merge lost.
            // The call retries internally, so getting here means identity is
            // unreachable.
            personhogStoreMergeCacheCounter.inc({ action: 'fence_resolve_failed' })
            throw new PersonMergeCallFailedError(
                `personhog merge fence resolve failed: ${error instanceof Error ? error.message : String(error)}`,
                error
            )
        }
        // A merge that settled while this was in flight has already repointed
        // whichever of these ids it named, and its answer is the newer one.
        // The keys still travel, because fencing a person the merge is about
        // to destroy is right either way; only the memo write is withheld,
        // and only for the ids that actually moved.
        for (const entry of resolved) {
            if (entry.person) {
                resolvedKeys.set(entry.distinctId, `${teamId}:${entry.person.id}`)
                const answered = `${teamId}:${entry.person.id}`
                if (!read.moved(`${teamId}:${entry.distinctId}`, answered)) {
                    this.memo.record(entry.teamId, entry.distinctId, entry.person, batchId, { readClass: 'checking' })
                }
            }
        }
        return resolvedKeys
    }

    /**
     * Writes every affected lane before the merge goes out, so the saga folds
     * people whose buffered changes already landed. The fence excludes other
     * writers, and passing it down keeps these writes from parking behind
     * this very merge.
     */
    private async writeLanesBeforeMerge(
        personKeys: string[],
        sagaOpIds: Set<string>,
        request: MergePersonsRequest,
        ownFence: Promise<void> | undefined
    ): Promise<void> {
        // `writeEntry` defers rather than throwing when a foreign fence
        // covers the person, so deferrals have to be counted to be seen.
        const pass = { deferrals: 0 }
        const captured: CapturedLane[] = []
        // Every fenced person's lane, whichever distinct id opened it. A lane
        // belongs to the person, and `entry.distinctId` only records which of
        // that person's ids folded first. The merge is about to destroy some
        // of these persons and discard whatever they still hold, so a lane
        // skipped here is a lost write.
        //
        // The reference backend reaches the same pending update through any
        // of a person's ids: its cache maps the id to the person and returns
        // that person's buffered write, which the merge then folds into the
        // survivor. Filtering by the merge's named ids would drop properties
        // Postgres keeps.
        for (const personKey of personKeys) {
            const entry = this.entries.get(personKey)
            if (!entry || entry.segments.length === 0) {
                continue
            }
            // Still in flight after the wait above means a redirect owns the
            // lane, and neither handle this merge waited on covers it: the
            // settle promise was cleared when the person turned out to be
            // gone, and the redirect registers under the survivor's key.
            // Waiting is not an option either, since the promise is cleared
            // precisely so a redirect can wait on merge fences without
            // closing a loop. So the merge defers and its batch redelivers,
            // which costs a round trip but never folds a person whose
            // buffered ops are unaccounted for.
            if (entry.inFlight) {
                pass.deferrals += 1
                personhogStoreFenceCounter.inc({ outcome: 'premerge_lane_in_flight' })
                continue
            }
            // Claimed as a flush claims, so a second merge fencing one of
            // these persons has a promise to wait on rather than folding
            // around a lane still on the wire.
            this.claimForWrite(entry)
            captured.push({ personKey, entry, segments: entry.segments.length })
        }
        if (captured.length === 0) {
            this.failOnDeferredLanes(pass)
            return
        }
        const limit = pLimit(this.options.maxConcurrentUpdates)
        const outcomes = await Promise.allSettled(
            captured.map(({ personKey, entry, segments }) =>
                limit(() => this.writeEntry(personKey, entry, segments, pass, ownFence))
            )
        )
        for (const outcome of outcomes) {
            if (outcome.status !== 'rejected') {
                continue
            }
            const error = outcome.reason
            // A leader fence on one of these persons is the one refusal this
            // call can answer, and who holds it decides the answer, in three
            // classes. Ownership is decided by the op id alone: only the
            // operation this request derives can be driven forward by
            // calling the saga, and one event legitimately owns several
            // operations (a fold and its trigger event's sequential merge,
            // a redelivered fold that re-batched differently), so a creator
            // match must not widen "own".
            if (error instanceof PersonhogFencedError) {
                if (error.fencingOpId !== undefined && sagaOpIds.has(error.fencingOpId)) {
                    // Our own saga holds the person, so the merge goes ahead:
                    // calling it is what drives that operation to completion.
                    // The lane is left as it is, because a merge fences only
                    // sources, and both source outcomes are covered already: a
                    // destroyed one is marked by reconcile and reaches the
                    // survivor, a skipped one drops before the fold.
                    personhogStoreFenceCounter.inc({ outcome: 'own_saga_holds_person' })
                    continue
                }
                // Any other holder takes the claim-race route the saga
                // reports as skipped_conflict: drop the merge with a warning
                // and keep the event's property updates. That includes a
                // sibling — a fence whose creator is this very event but
                // whose operation this request cannot reconstruct, such as a
                // parked fold this delivery re-batched away from. A sibling
                // cannot be driven forward from here (only a retry under its
                // own op id resumes it), and a parked one never settles by
                // itself, so deferring to redelivery could loop without
                // bound. The classification still travels: the label and the
                // error name whether our own event's earlier work or a
                // stranger holds the person, which is the difference between
                // retrying the parked op and investigating a conflict.
                const sibling =
                    error.fencingCreatorEventUuid !== undefined &&
                    error.fencingCreatorEventUuid.toLowerCase() === request.eventUuid.toLowerCase()
                personhogStoreFenceCounter.inc({
                    outcome: sibling ? 'sibling_op_holds_person' : 'foreign_lifecycle_op',
                })
                throw new PersonClaimedByLifecycleOpError(
                    `merge: person ${error.personId} is held by lifecycle op ${error.fencingOpId ?? 'unknown'}` +
                        (sibling ? ' (a sibling operation of this same event)' : ''),
                    request.teamId
                )
            }
            // Any other failure leaves the merge unattempted. The typed
            // wrapper is what makes the merge service fail the batch;
            // unwrapped, a generic catch would ack and drop the merge.
            throw new PersonMergeCallFailedError(
                `personhog pre-merge write failed: ${error instanceof Error ? error.message : String(error)}`,
                error
            )
        }
        this.failOnDeferredLanes(pass)
    }

    /**
     * Fails the merge when any lane it must write went unwritten, which would
     * leave ops buffered while the saga folds their person. Redelivery replays
     * the batch once whatever held the lane lets go.
     */
    private failOnDeferredLanes(pass: { deferrals: number }): void {
        if (pass.deferrals === 0) {
            return
        }
        throw new PersonMergeCallFailedError(
            `personhog pre-merge write left ${pass.deferrals} lane(s) unwritten`,
            undefined
        )
    }

    /**
     * Every op id `runMerge` could send: the plain derivation and the conflict
     * suffixes its retries carry. A fence held by any of them belongs to this
     * request's own saga, including from an earlier delivery, since every id
     * derives from the event rather than from this delivery. This set is the
     * ownership test; the fence's creator event uuid cannot replace it,
     * because the creator identifies the event and an event can own several
     * operations. The creator classifies same-event siblings instead.
     */
    private sagaOpIdCandidates(request: MergePersonsRequest): Set<string> {
        const moveLimit = moveLimitFor(request.mergeMode, this.options.syncMergeMoveLimit)
        const sources = request.sources.map((source) => source.distinctId)
        const candidates = new Set([mergeOpIdFromRequest(request.teamId, request.eventUuid, sources, moveLimit)])
        for (let attempt = 1; attempt < defaultRetryConfig.MAX_RETRIES_DEFAULT; attempt++) {
            candidates.add(
                mergeOpIdFromRequest(request.teamId, `${request.eventUuid}#conflict${attempt}`, sources, moveLimit)
            )
        }
        return candidates
    }

    private async runMerge(
        request: MergePersonsRequest,
        batchId: number,
        beliefs: Map<string, string>
    ): Promise<MergePersonsResult> {
        // Verdicts are recorded durably against the op id, so a retry would
        // replay the same answer. A skipped_conflict is transient, so each
        // retry salts a counter suffix into the derivation for a fresh look,
        // and exhaustion throws the claim error Postgres throws. It cannot
        // double-merge: a conflict verdict proves the aborted op destroyed
        // nothing, and a fresh op against an already merged graph settles as
        // noop_same_person. Retrying is for a single source only, because a
        // fold's fresh op id would re-run the sources that did settle.
        const singleSource = request.sources.length === 1
        let conflictRetries = 0
        let result
        while (true) {
            try {
                result = await this.repository.mergePersons(
                    {
                        teamId: request.teamId,
                        targetDistinctId: request.targetDistinctId,
                        sources: request.sources,
                        eventSet: request.eventOps.set,
                        eventSetOnce: request.eventOps.setOnce,
                        // Event uuids are client-supplied and the op keyspace is
                        // global, so a raw uuid could collide with another team's
                        // recorded op. The uuidv5 derivation scopes it per team,
                        // and the source list keeps a fold and the single-source
                        // merges it falls back to on separate keys.
                        opId: mergeOpIdFromRequest(
                            request.teamId,
                            conflictRetries === 0
                                ? request.eventUuid
                                : `${request.eventUuid}#conflict${conflictRetries}`,
                            request.sources.map((source) => source.distinctId),
                            moveLimitFor(request.mergeMode, this.options.syncMergeMoveLimit)
                        ),
                        allowIdentifiedSources: request.allowIdentifiedSources,
                        // ASYNC and LIMIT carry a limit the constructor never
                        // sees, and it reaches BigInt() here, so
                        // determineMergeMode holds it to the same contract at
                        // startup.
                        moveLimit: moveLimitFor(request.mergeMode, this.options.syncMergeMoveLimit),
                        createdAtMs: request.createdAtMs,
                        // The raw event uuid, which the op id only carries as a
                        // one-way uuidv5 derivation. The saga stamps it on a
                        // person it births, matching what the Postgres backend
                        // writes at creation.
                        creatorEventUuid: request.eventUuid,
                    },
                    CALLER_TAG
                )
            } catch (error) {
                // A verdict, not an unknowable failure: redelivery meets the
                // same validation forever, so wrapping it would wedge the
                // partition on one malformed id, and it propagates raw to be
                // acked loudly. It is not always pre-durable, though — the
                // entrance commits attaches before the property push, whose
                // size ceiling also answers InvalidArgument — so the acked
                // loss can be the event's properties alone, with the attaches
                // standing.
                if (error instanceof ConnectError && error.code === Code.InvalidArgument) {
                    personhogStoreMergeCallFailedCounter.inc({ error: 'InvalidArgumentSettled' })
                    throw error
                }
                // The replay guard's refusal is deterministic: the op id
                // names a different recorded merge, and every redelivery
                // meets the same comparison forever, so wrapping it would
                // wedge the partition on one duplicated event uuid. Like
                // InvalidArgument it propagates raw to be acked loudly. It
                // refuses before any durable work, so the team view stands.
                // Keyed on the refusal's reason slug rather than the status
                // code, because a semantic refusal can also arrive from a
                // later saga step — after sources were sealed or flipped —
                // where skipping the invalidation below would be wrong.
                if (
                    error instanceof ConnectError &&
                    error.metadata.get(SEMANTIC_REFUSAL_METADATA_KEY) === SEMANTIC_REFUSAL_OP_ID_REUSED
                ) {
                    personhogStoreMergeCallFailedCounter.inc({ error: 'OpIdReusedSettled' })
                    throw error
                }
                // The saga is resumable, so a failed call may still have
                // sealed sources or flipped their ids onto the survivor.
                // How far it got is unknowable, so invalidate as if it had.
                this.invalidateTeamAfterFailedMerge(request.teamId)
                // No verdict arrived, so an ack would lose the merge whenever
                // the saga did not commit. The typed wrapper makes the merge
                // service fail the batch, and redelivery replays the saga
                // idempotently. Only the call is wrapped, so a bug in
                // post-verdict processing surfaces as itself.
                personhogStoreMergeCallFailedCounter.inc({
                    // gRPC codes are a closed set; naming them separates a
                    // replay-guard bounce from transport trouble at a glance.
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
            // Every attempt's verdicts count, or a conflicted attempt that
            // never surfaces would be invisible.
            for (const source of result.results) {
                personhogStoreMergeOutcomeCounter.inc({ outcome: source.outcome })
            }
            if (singleSource && result.results[0]?.outcome === 'skipped_conflict') {
                conflictRetries += 1
                if (conflictRetries >= defaultRetryConfig.MAX_RETRIES_DEFAULT) {
                    throw new PersonClaimedByLifecycleOpError(
                        'merge saga: a live lifecycle operation holds a person in this merge',
                        request.teamId
                    )
                }
                await new Promise((resolve) =>
                    setTimeout(resolve, defaultRetryConfig.RETRY_INTERVAL_DEFAULT * conflictRetries)
                )
                continue
            }
            break
        }
        const touched = result.results
            .filter((source) => ['merged', 'attached', 'noop_same_person'].includes(source.outcome))
            .map((source) => source.sourceDistinctId)
        const merged = result.results.filter((source) => source.outcome === 'merged')
        this.reconcileMergedPersons(
            request.teamId,
            merged.map((source) => ({
                personKey: source.sourcePersonId != null ? `${request.teamId}:${source.sourcePersonId}` : undefined,
                distinctKey: `${request.teamId}:${source.sourceDistinctId}`,
                // What this pod believed the id named before the merge's own
                // resolve overwrote the memo edge: a stale belief's lane
                // holds ops folded for a person the server may have merged
                // under a different name, and reconcile's memo lookup can no
                // longer see it.
                beliefKey: beliefs.get(source.sourceDistinctId),
            })),
            result.survivor ? `${request.teamId}:${result.survivor.id}` : undefined,
            batchId
        )
        // A fold that skipped any source on a lifecycle conflict, the move
        // limit, or a definitive refusal aborts, after the reconcile above
        // has taken account of the sources that did merge. The Postgres
        // fold is all-or-nothing — a held person or an over-limit source
        // aborts its whole transaction — so every event gets its own
        // sequential decision: a conflicted source retries under salted op
        // ids, an over-limit one receives its merge-mode verdict (DLQ or
        // redirect), a refused one settles as its own warned loss, and an
        // already-merged one settles as a same-person no-op. Executing the
        // fold instead would ack the skipped sources with nothing behind
        // them, which is a durability decision Postgres never makes — an
        // aborted fold's response still carries a survivor, but only as the
        // person the event's writes were delivered to, never as an executed
        // merge. Retrying the whole fold under a fresh op id is not an
        // option either, since it would re-run the sources that settled.
        if (!singleSource) {
            const overLimit = result.results.some((source) => source.outcome === 'skipped_move_limit')
            const conflicted = result.results.some((source) => source.outcome === 'skipped_conflict')
            const refused = result.results.some((source) => source.outcome === 'skipped_refused')
            // Abort-ness is reconstructed from verdict names, so the net has
            // to catch every aborted shape. An error verdict with no merged
            // source alongside it can only be an abort: completion implies
            // at least one source folded, since the all-fell-out case aborts
            // before the fold. This is the belt for shapes the named checks
            // miss — the vanished-source abort still records error, and so
            // do rows frozen by the vocabulary this branch briefly shipped.
            const errored = merged.length === 0 && result.results.some((source) => source.outcome === 'error')
            if (overLimit || conflicted || refused || errored) {
                personhogStoreMergeCacheCounter.inc({ action: 'fold_skip_abort' })
                if (result.survivor && typeof result.survivor.version === 'number') {
                    // The saga's partial folds and the aborted-writes
                    // delivery moved the leader past this version even
                    // though the fold aborted; the standing baseline must
                    // not go on serving from before it.
                    this.memo.dropBaselineBehindWrites(
                        `${request.teamId}:${result.survivor.id}`,
                        result.survivor.version
                    )
                }
                return {
                    survivor: null,
                    results: [],
                    foldAborted: overLimit ? 'limit' : conflicted ? 'conflict' : refused ? 'refused' : 'error',
                }
            }
        }
        let survivor = result.survivor
        if (result.survivor) {
            // Update authority enters the memo only through leader reads and
            // own-write answers, never through a response document: a fold's
            // survivor is frozen at its commit and replays for the retention
            // window, and every other shape answers the sync plane's own
            // resolve, which lags the leader the way any identity answer
            // does. Classifying a later op against either can suppress a
            // genuinely new value as no-change. So the survivor's version
            // only floors the key (state the leader provably passed), and
            // one leader read supplies the document the batch folds
            // against — the same read the update fetch and the create path
            // pay.
            const survivorKey = `${request.teamId}:${result.survivor.id}`
            this.memo.dropBaselineBehindWrites(
                survivorKey,
                typeof result.survivor.version === 'number' ? result.survivor.version : undefined
            )
            // The one read that installs authority outside a read handle,
            // so it carries the team-epoch stamp by hand: a concurrent
            // merge failing without a verdict bumps the epoch because which
            // persons died is unknowable, and a refresh served before that
            // failure must not reinstall state the invalidation dropped.
            // The epoch is the one stamp taken — destruction is covered by
            // the marks record() consults, and a concurrent gone-arm id
            // bump is not: an edge re-recorded over one heals through the
            // tombstone redirect, which is the accepted cost of skipping a
            // full handle here.
            const epochBefore = this.memo.epochOf(request.teamId)
            let refreshed: InternalPerson | null
            try {
                refreshed = await this.repository.fetchPersonById(request.teamId, result.survivor.id, CALLER_TAG)
            } catch (error) {
                // The verdict is durable and reconciled; only the refresh is
                // lost. Installing nothing degrades to read amplification —
                // later update-class reads pay the leader — while throwing
                // would fail a batch whose merge committed. The caller still
                // folds this event against the response document, which is
                // safe for the merge's own ops: the request carried them and
                // the service already applied them durably.
                personhogStoreMergeCacheCounter.inc({ action: 'survivor_refresh_failed' })
                logger.warn('🤔', 'merge survivor refresh failed; batch proceeds without a leader document', {
                    team_id: request.teamId,
                    person_id: result.survivor.id,
                    error: String(error),
                })
                return {
                    survivor: result.survivor,
                    results: result.results,
                    survivorNeedsUpdate: !(result.survivorWasBorn && result.survivor?.is_identified === true),
                }
            }
            if (refreshed === null) {
                // The survivor itself is gone — destroyed by a later merge or
                // deletion the response predates. The same stamps the create
                // path applies on this signal: the marks keep the dead
                // document out of the memo and the flush's destroyed-person
                // rescue carries any folded ops through the tombstone
                // redirect.
                personhogStoreDeathStampCounter.inc({ site: 'merge_refresh_null' })
                this.memo.markDestroyed(survivorKey)
                this.memo.bumpId(`${request.teamId}:${request.targetDistinctId}`)
                for (const distinctId of touched) {
                    this.memo.bumpId(`${request.teamId}:${distinctId}`)
                }
            } else if (this.memo.epochOf(request.teamId) !== epochBefore) {
                // The team view was invalidated while the read was on the
                // wire, so this answer may predate destructions nobody
                // verdicted to this pod. Installing nothing degrades to
                // read amplification, the same as a failed read; the caller
                // still folds this event safely, since its ops are durable
                // server-side in every survivor-returning shape. A stamp
                // swept at the watermark mid-read trips this too — a
                // one-shot spurious decline in the same safe direction, so
                // the counter reads as an upper bound on invalidations.
                personhogStoreMergeCacheCounter.inc({ action: 'refresh_stale_epoch' })
                survivor = newerSurvivor(result.survivor, refreshed)
            } else {
                // The leader's document is at or past everything this merge
                // committed, so read-your-write holds, and these ids serve
                // the update read class through it.
                this.memo.record(request.teamId, request.targetDistinctId, refreshed, batchId, {
                    readClass: 'update',
                })
                for (const distinctId of touched) {
                    this.memo.record(request.teamId, distinctId, refreshed, batchId, { readClass: 'update' })
                }
                survivor = newerSurvivor(result.survivor, refreshed)
            }
        }
        return {
            survivor,
            results: result.results,
            // Only a newborn that is also identified has everything the
            // follow-up update would apply, which is the state the Postgres
            // backend's own creation leaves behind when it reports the same.
            // A birth whose every source was skipped is not identified: the
            // flip rests on a source settling as attached or as the same
            // person, and there was none, so the follow-up is the only thing
            // that will ever identify that person. Only the inline
            // settlement reports a birth, so no saga is involved. Judged on
            // the response document rather than the refreshed one, because
            // the question is what the merge itself left behind.
            survivorNeedsUpdate: !(result.survivorWasBorn && result.survivor?.is_identified === true),
        }
    }

    /**
     * Whether a lane still holds ops no write has taken. Not the same as an
     * entry existing: an entry outlives its segments, since a flush drains
     * one while the batch still references it and a merge discard empties
     * one. A drained lane holds nothing a fetch could be missing, so it must
     * not go on winning against one.
     */
    private hasUnwrittenOps(personKey: string): boolean {
        return (this.entries.get(personKey)?.segments.length ?? 0) > 0
    }

    /**
     * A service document brought up to what this batch has folded but not
     * yet sent, which is the view the memo answers reads with. A segment
     * leaves the lane before its write goes out, so the ops replayed here
     * are exactly the ones the leader has not been told about: none of them
     * can already be in the document, and none of them can be missing from
     * both.
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
     * A direct diff update, applied rather than folded: the caller resolved
     * the diff already, so it maps onto the leader's folded-update RPC. Only
     * diff-expressible fields of `otherUpdates` are supported; anything else
     * has no RPC field and fails loudly rather than dropping silently.
     */
    /**
     * Deliberately outside the local fence and lane protocol that folds
     * honor: a direct write racing a remote merge is stopped by the leader's
     * own fence instead, which fails the batch to redelivery. Local fences
     * order buffered work; this path buffers nothing.
     */
    async updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        _distinctId: string,
        _batchId: number,
        _forceUpdate?: boolean,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        const read = this.memo.beginRead(person.team_id, _batchId, [`${person.team_id}:${_distinctId}`])
        const unsupported = Object.keys(otherUpdates).filter((key) => key !== 'is_identified' && key !== 'last_seen_at')
        if (unsupported.length > 0) {
            // The field names are the whole diagnostic value here: the error
            // exists to say this backend cannot write something, and without
            // naming it an operator cannot tell which caller to fix.
            // One per field rather than one for the set: the field names come
            // from a fixed schema, so counting them individually keeps the
            // label bounded by that schema instead of by its power set, and
            // aggregates the way an operator would ask the question.
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
            },
            CALLER_TAG
        )
        const directKey = `${person.team_id}:${person.id}`
        if (!updated) {
            // A null document with the write applied is the same fact the
            // lane path floors on: the leader moved past whatever we held,
            // and a read served before this write must not refill the view
            // with pre-write state. A null document without an applied
            // write is a genuine no-op and leaves the baseline alone.
            if (applied) {
                // Unlike the lane path, nothing marks this write in flight,
                // so a concurrent read can install a post-apply baseline
                // before this runs and held + 1 would overshoot the leader
                // by one. Unreachable today — the leader answers a document
                // on every applied write — so this arm is cross-version
                // defense, and an overshoot costs re-reads, never a loss.
                const held = this.memo.viewOfPerson(directKey)?.version
                if (typeof held === 'number') {
                    this.memo.dropBaseline(directKey, held + 1)
                } else if (typeof person.version === 'number') {
                    // No memo view, but the caller's document is a sound
                    // anchor: the leader held its version when it was read,
                    // and this write moved past whatever the leader held.
                    this.memo.dropBaseline(directKey, person.version + 1)
                } else {
                    this.memo.raiseFloorPastAppliedWrite(directKey)
                }
            }
            return [person, [], false]
        }
        // Every write installs what the leader answered, or the baseline
        // goes on naming the read it was built from. This path bypasses the
        // lane, so any ops still buffered there replay on top.
        //
        // A merge that rewrote the memo meanwhile may have destroyed this
        // person, and installing then would resurrect a baseline reconcile
        // just deleted. Leaving the old one is no better, since it names a
        // read this write has already superseded, so the batch gives up its
        // view and the next read rebuilds it from the leader.
        const personKey = directKey
        if (!read.moved(`${person.team_id}:${_distinctId}`)) {
            // The edge is recorded with the install so the baseline is
            // referenced by this batch and released with it; an unreferenced
            // baseline would outlive every batch, since eviction only runs
            // when a reference or a lane lets go.
            this.memo.recordResolution(_batchId, `${person.team_id}:${_distinctId}`, personKey)
            this.memo.offerBaseline(personKey, updated, 'own-write')
        } else {
            // The answer's version floors the drop: a read served before
            // this write applied and delivered after it would otherwise
            // find the absence and refill it with pre-write state, and a
            // later event whose $set matches that state would be filtered
            // as no-change while the leader holds something newer.
            this.memo.dropBaseline(personKey, updated.version)
        }
        // No ClickHouse message: the leader's changelog is this backend's
        // person feed, so emitting here would double-publish.
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
            return this.memo.lookup(entry.teamId, entry.distinctId, 'checking') === undefined
        })
        if (unresolved.length === 0) {
            return
        }
        // The caller holds these batches' handles, so they are live now. The
        // response lands later and may find them released, and anything
        // recorded for a released batch is held by something that can never
        // let go of it.
        for (const entry of unresolved) {
            this.prefetchingBatches.add(entry.batchId)
        }
        // Captured per id before the resolve goes out: a merge speaking for
        // one of them while this response is in flight makes that fill
        // suspect, because the absence it would fill may be a resolution the
        // merge released. The others are unaffected and still fill.
        const reads = new Map(
            unresolved.map((entry) => [
                `${entry.teamId}:${entry.distinctId}`,
                this.memo.beginRead(entry.teamId, entry.batchId, [`${entry.teamId}:${entry.distinctId}`]),
            ])
        )
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
                        const distinctKey = `${entry.teamId}:${entry.distinctId}`
                        const read = reads.get(distinctKey)
                        if (read === undefined || read.moved(distinctKey) || !this.prefetchingBatches.has(batchId)) {
                            return
                        }
                        if (!entry.person) {
                            this.memo.record(entry.teamId, entry.distinctId, null, batchId, { readClass: 'update' })
                            return
                        }
                        const person = await this.repository.fetchPersonById(entry.teamId, entry.person.id, CALLER_TAG)
                        // Re-checked after this read as well as before it: the
                        // batch can release while the read is in flight, and
                        // recording for a released batch recreates its key set
                        // so nothing ever releases it again.
                        if (
                            read.moved(distinctKey, `${entry.teamId}:${entry.person.id}`) ||
                            !this.prefetchingBatches.has(batchId)
                        ) {
                            return
                        }
                        // Fill-only: this response raced everything the batch
                        // did since the request went out.
                        this.memo.record(entry.teamId, entry.distinctId, person, batchId, {
                            readClass: 'update',
                            fillOnly: true,
                        })
                    })
                )
            )
        } catch (error) {
            // Counted, because the degradation is silent otherwise: every id
            // falls back to resolving on first touch, which costs a round
            // trip per event instead of one per batch and looks like nothing
            // more than latency.
            personhogStorePrefetchFailedCounter.inc()
            logger.warn('personhog prefetch failed; resolution falls back to first touch', { error })
        }
    }

    /**
     * Writes the batch's folded lanes to the leader, one entry per person,
     * segments in order. No Postgres fallback and nothing publishes: the
     * leader's changelog is this backend's person feed. A missing person
     * redirects to whatever its distinct id resolves to now; a person
     * genuinely gone and a size rejection are counted and dropped, since
     * neither can succeed on retry. Anything else fails the flush.
     *
     * Passes serialize. A pass snapshots each lane's segment count and
     * removes segments as they land, so a partial failure keeps what it did
     * not attempt for a later pass to write again.
     *
     * A lane with no update-worthy change is suppressed rather than written,
     * as Postgres does. `triggersUpdate` accumulates across batches, so one
     * batch's real change carries a sibling's filtered-only fold with it.
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
        // return while any lane still holds unwritten segments. A lane parked
        // behind a merge is waited out and written, or the pass fails and the
        // batch redelivers; acking past one would commit offsets over writes
        // that exist only in this process.
        //
        // One deadline across every round, since per-round budgets would add
        // up on a pass that already runs at the end of the request.
        const waitDeadline = Date.now() + this.options.fenceWaitMs
        for (let round = 0; ; round++) {
            const pass = { deferrals: 0 }
            await this.writeEligibleLanes(round === 0, pass)
            // The loop keys off what THIS round left behind, not what is
            // parked at this instant: a fence releasing while other writes
            // were still in flight leaves a deferred lane neither fenced nor
            // in flight — invisible to a parked-only predicate — and a
            // return here would ack over its unwritten ops.
            if (pass.deferrals === 0) {
                // No FlushResults: the leader's changelog is the ClickHouse
                // person feed, so a flush publishes nothing — writing the
                // segments is the whole job.
                return []
            }
            if (round >= FLUSH_MAX_MERGE_WAIT_ROUNDS) {
                personhogStoreFlushCounter.inc({ outcome: 'parked_exhausted' })
                throw new Error(
                    `flush cannot complete: ${pass.deferrals} lanes deferred behind merges that did not settle`
                )
            }
            // Wait out whatever is still fenced. Concurrently, because the
            // fences overlap and waiting serially would cost fenced-lane
            // count times the ceiling. Settled rather than raced, so one
            // lane's timeout does not leave the others rejecting unobserved.
            const waited = await Promise.allSettled(
                [...this.entries]
                    .filter(([, entry]) => entry.segments.length > 0)
                    .map(([personKey]) => this.awaitFences(personKey, undefined, waitDeadline))
            )
            const failed = waited.find((wait) => wait.status === 'rejected')
            if (failed !== undefined) {
                throw failed.reason
            }
        }
    }

    private async writeEligibleLanes(countDeferrals: boolean, pass: { deferrals: number }): Promise<void> {
        // Entries are never removed to be written. A pass records the
        // segment count, marks the lane in flight, and truncates exactly that
        // many on success, so a failure leaves the entry as it was with no
        // claim to strand. No await in this block: the snapshot is atomic.
        const captured: CapturedLane[] = []
        for (const [personKey, entry] of this.entries) {
            if (entry.segments.length === 0) {
                continue
            }
            if (entry.inFlight) {
                // A backstop the fence check below currently subsumes, since
                // capture is synchronous and passes serialize. Kept because
                // the deferral is what stops a flush resolving over segments
                // a failed merge hands back, which must not depend on the two
                // guards staying in step.
                pass.deferrals += 1
                continue
            }
            // A fenced person's merge is on the wire. Writing its lane now
            // could hit the tombstone and redirect to the survivor before
            // reconcile has decided the person's fate. The drain loop waits
            // the merge out and writes the lane before the flush returns.
            if (this.fences.has(personKey)) {
                pass.deferrals += 1
                if (countDeferrals) {
                    personhogStoreFlushCounter.inc({ outcome: 'deferred_fenced' })
                }
                continue
            }
            this.claimForWrite(entry)
            captured.push({ personKey, entry, segments: entry.segments.length })
        }
        const limit = pLimit(this.options.maxConcurrentUpdates)
        const outcomes = await Promise.allSettled(
            captured.map(({ personKey, entry, segments }) =>
                limit(() => this.writeEntry(personKey, entry, segments, pass))
            )
        )
        const failed = outcomes.find((outcome): outcome is PromiseRejectedResult => outcome.status === 'rejected')
        if (failed) {
            throw failed.reason
        }
    }

    /**
     * Clears the in-flight mark and retires an entry with nothing left.
     * Runs on every exit from a write, including a throw: a mark left set
     * would make every later pass skip the entry and strand its ops.
     */
    private releaseWritten(personKey: string, entry: OpsLaneEntry): void {
        entry.inFlight = false
        entry.settleWrite?.()
        entry.settleWrite = undefined
        entry.directWriteSettled = undefined
        if (entry.segments.length > 0) {
            // A failed write on an entry a shadow release abandoned would
            // otherwise persist as ownerless retry work no later abandon
            // visits; the settle is the last hand that holds it.
            if (entry.abandoned && !this.entryHeldByAnyBatch(personKey) && this.entries.get(personKey) === entry) {
                personhogStoreShadowShedCounter.inc(entry.segments.length)
                entry.segments.length = 0
                this.retireEntry(personKey)
            }
            return
        }
        entry.triggersUpdate = false
        // A drained entry no batch still references was held open only to
        // protect its unwritten ops; now it can go. Identity-guarded: a
        // stale finalizer (an old write settling after the entry was retired
        // and recreated) must not retire the new entry's unwritten ops.
        if (!this.entryHeldByAnyBatch(personKey) && this.entries.get(personKey) === entry) {
            this.retireEntry(personKey)
        }
    }

    private async writeEntry(
        personKey: string,
        entry: OpsLaneEntry,
        segments: number,
        pass?: { deferrals: number },
        /**
         * The fence this write's own merge installed, if a merge issued it.
         * Parking behind it would be parking behind itself. Tested by
         * identity, never by key, so a second merge on the same person still
         * holds this write back.
         */
        ownFence?: Promise<void>
    ): Promise<void> {
        // Capture marked this lane, but execution can begin macrotasks later
        // behind a pLimit slot. A merge can fence the person in that gap and
        // cannot see a write with no promise yet, so the fence is re-checked
        // at the moment writing starts. A fenced lane defers to the drain
        // loop, which writes it once the merge has released.
        if (this.isHeldByOther(personKey, ownFence)) {
            // A merge's own pre-merge write is not a flush, and conflating
            // the two would file the signal that a merge is contending under
            // flush pressure.
            if (ownFence !== undefined) {
                personhogStoreFenceCounter.inc({ outcome: 'premerge_write_deferred' })
            } else {
                personhogStoreFlushCounter.inc({ outcome: 'deferred_fenced_at_start' })
            }
            if (pass) {
                pass.deferrals += 1
            }
            this.releaseWritten(personKey, entry)
            return
        }
        try {
            // Suppressing a filtered-only lane is a flush rule, not a merge
            // one. The reference backend reads the source through its cache,
            // so those pending values are already folded into the survivor's
            // properties before it clears anything; dropping them here would
            // lose a write it keeps. A merge-issued write is a forced write.
            if (!entry.triggersUpdate && ownFence === undefined) {
                if (!this.memo.isDestroyed(personKey)) {
                    personhogStoreFlushCounter.inc({ outcome: 'filtered' })
                    this.dropLeadingSegments(entry, segments)
                    return
                }
                // Filtered-only was decided against the document of a person
                // a merge has destroyed, which is the wrong document: the
                // reference backend classifies against the survivor it reads
                // through its cache. Writing lets the tombstone redirect
                // carry the ops there, where the leader applies them against
                // the true state.
                personhogStoreFlushCounter.inc({ outcome: 'filtered_rescued_destroyed' })
            }
            // What this pass still owes, decremented as segments leave the
            // lane by being written or dropped. Array length is no
            // substitute: folds arriving during a redirect's waits inflate it
            // with segments this pass never attempted and must not discard.
            const progress = { remaining: segments }
            // A size rejection removes only the rejected unit and the rest
            // of the snapshot is still writable, which the flush must not
            // ack over. Terminates: every iteration writes the remainder,
            // drops a unit, enters the redirect phase once, or throws.
            let viaRedirect = false
            // Opened once for the lane, not once per redirect: a size
            // rejection re-enters the redirect for every dropped unit, and a
            // fresh deadline each time would let one lane hold a flush for a
            // multiple of the ceiling.
            const fenceDeadline = Date.now() + this.options.fenceWaitMs
            while (progress.remaining > 0) {
                try {
                    if (viaRedirect) {
                        const outcome = await this.redirectToSurvivor(entry, progress, fenceDeadline, ownFence)
                        personhogStoreFlushCounter.inc({
                            outcome: { written: 'redirected', gone: 'not_found', size_violation: 'size_violation' }[
                                outcome
                            ],
                        })
                        if (outcome === 'gone') {
                            // The one arm that permanently discards a lane's
                            // ops: the person was deleted and its id resolves
                            // to nobody, so there is no row for them. Named
                            // here because the counter alone cannot say whose
                            // data went.
                            logger.warn('🤔', 'lane dropped: its person was deleted and its id resolves to nobody', {
                                team_id: entry.teamId,
                                person_id: entry.personId,
                                distinct_id: entry.distinctId,
                                segments: progress.remaining,
                            })
                            this.dropLeadingSegments(entry, progress.remaining)
                            break
                        }
                        if (outcome === 'size_violation') {
                            // Only the rejected unit can never succeed; the
                            // remainder re-enters the redirect with the person
                            // still gone. Deliberately not Postgres's unit:
                            // one oversized row aborts its whole batch
                            // statement and every person in that flush is
                            // dropped with it, which is not a loss worth
                            // reproducing.
                            this.dropLeadingSegments(entry, 1)
                            progress.remaining -= 1
                            continue
                        }
                        break
                    }
                    await this.writeSegments(entry, entry.personId, progress)
                    personhogStoreFlushCounter.inc({ outcome: 'success' })
                    break
                } catch (error) {
                    if (error instanceof NoRowsUpdatedError) {
                        // The person was merged or deleted since the fold.
                        // Settled before the redirect phase, because the
                        // redirect waits on merge fences and a merge waiting
                        // on this promise would close a cycle. A size-drop
                        // resume keeps it pending, since that write is still
                        // a direct one the merge must order behind.
                        entry.settleWrite?.()
                        entry.settleWrite = undefined
                        entry.directWriteSettled = undefined
                        viaRedirect = true
                        continue
                    }
                    if (error instanceof PersonhogPropertiesSizeError) {
                        // The rejected segment can never succeed, so it goes
                        // and the loop writes the remainder now. Postgres
                        // loses more here — one oversized row aborts its whole
                        // batch statement, taking every other person in that
                        // flush with it — and that is not a loss worth
                        // reproducing.
                        //
                        // The customer-facing warning comes from the leader,
                        // which emits PersonPropertiesSizeViolation on this
                        // same rejection but throttles it to one per team per
                        // hour. The log line is what attributes the
                        // individual discard, which the throttle would
                        // otherwise swallow.
                        personhogStoreFlushCounter.inc({ outcome: 'size_violation' })
                        // Nothing to repair in the memo: the baseline is a
                        // leader document and never counted these ops, so
                        // dropping them leaves the view reading as though
                        // they never happened.
                        logger.warn('🤔', 'leader refused a write on properties size; the ops are discarded', {
                            team_id: entry.teamId,
                            person_id: entry.personId,
                            distinct_id: entry.distinctId,
                        })
                        this.dropLeadingSegments(entry, 1)
                        progress.remaining -= 1
                        continue
                    }
                    // A redirect failure already recorded the outcome that
                    // named it, so counting again here would file one failure
                    // twice and leave 'error' unreadable as the unclassified
                    // bucket it is meant to be.
                    if (!(error instanceof CountedRedirectError)) {
                        personhogStoreFlushCounter.inc({ outcome: 'error' })
                        // The outcome series is one bucket for everything
                        // unclassified, which is the bucket an operator most
                        // needs broken down: a leader fence, a permanent
                        // rejection, and a transport blip need different
                        // answers and read identically without this.
                        personhogStoreFlushErrorCounter.inc({ error: flushErrorClass(error) })
                    }
                    if (error instanceof PersonhogFencedError) {
                        // An expected coordination outcome, not a flush
                        // malfunction: a live holder settles and releases, a
                        // ghost fence is healed by the very bounce that
                        // produced this error, and the redelivery then flows.
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
                    // The unwritten segments stay in the entry, so the next
                    // pass writes them again rather than losing writes the
                    // batch holds.
                    throw error
                }
            }
        } finally {
            this.releaseWritten(personKey, entry)
        }
    }

    /**
     * Marks a lane as this writer's and arms the promise a merge waits on.
     * Armed at claim time, not when the write starts, so a merge cannot skip
     * a lane that is claimed but has yet to reach its concurrency slot.
     */
    private claimForWrite(entry: OpsLaneEntry): void {
        entry.inFlight = true
        entry.settleWrite = undefined
        entry.directWriteSettled = new Promise((resolve) => {
            entry.settleWrite = resolve
        })
    }

    /** An authoritative document with a lane's still-unwritten ops replayed on top. */
    /**
     * A service document with a lane's unsent ops applied on top, which is
     * what a read of that person should answer.
     *
     * Built from the same refine-and-apply pair the Postgres backend writes
     * through, rather than a second reading of the leader's rules: its
     * `$unset` already skips a key the op itself introduced, which is the
     * leader's pre-op-document rule, and it declines a denied event's
     * properties. Outcomes stay unrecorded because these events were counted
     * when they were folded.
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

    private async writeOne(entry: OpsLaneEntry, personId: string, ops: EventOps): Promise<InternalPerson | null> {
        const { person } = await this.repository.updatePersonProperties(
            {
                teamId: entry.teamId,
                personId,
                eventName: ops.eventName,
                setProperties: ops.set,
                setOnceProperties: ops.setOnce,
                unsetProperties: ops.unset,
                isIdentified: ops.isIdentified,
                lastSeenAtMs: ops.lastSeenAtMs,
            },
            CALLER_TAG
        )
        return person
    }

    /** Removes the lane's leading segments once written or judged unwritable. */
    private dropLeadingSegments(entry: OpsLaneEntry, count: number): void {
        entry.segments.splice(0, count)
    }

    /**
     * Writes a lane's leading segments, removing each as it lands so a
     * partial failure discards nothing unattempted.
     */
    private async writeSegments(
        entry: OpsLaneEntry,
        personId: string,
        progress: { remaining: number },
        applied?: { version?: number }
    ): Promise<void> {
        const count = Math.min(progress.remaining, entry.segments.length)
        for (let written = 0; written < count; written++) {
            // The segment stays in the lane while it is on the wire, so a
            // reader still sees the batch's own write. It leaves the lane in
            // the same synchronous step that installs the leader's answer,
            // so no reader can observe the op counted twice or not at all.
            const answer = await this.writeOne(entry, personId, entry.segments[0])
            this.dropLeadingSegments(entry, 1)
            progress.remaining -= 1
            // Reported through the holder rather than the return value so a
            // later segment's throw does not lose what earlier ones learned:
            // the caller's floor is only as good as the furthest answer.
            if (applied !== undefined && typeof answer?.version === 'number') {
                applied.version = Math.max(applied.version ?? 0, answer.version)
            }
            // The document the leader answered is this person's state as of
            // the write, so the baseline tracks the leader rather than the
            // last read. Without it a read issued before this write and
            // delivered after it carries the same version as the baseline,
            // and nothing can tell the two apart. A response carrying no
            // document leaves the baseline naming a version the leader has
            // moved past, which the next read has to replace.
            //
            // Only where the lane owns the person. A redirect writes to a
            // survivor whose baseline answers for its own lane, and this
            // lane's ops are not that lane's; the redirect drops that
            // survivor's baseline once it is done.
            if (personId === entry.personId) {
                const personKey = `${entry.teamId}:${personId}`
                if (answer !== null) {
                    this.memo.offerBaseline(personKey, answer, 'own-write')
                } else {
                    // The call returned without throwing, so the write
                    // applied and the leader moved past what we held; the
                    // held version plus one floors the drop against a read
                    // served before the write and delivered after it. With
                    // no baseline to read a version from, the existing
                    // floor still advances by one, since the applied write
                    // moved the leader past whatever that floor recorded.
                    const held = this.memo.viewOfPerson(personKey)?.version
                    if (typeof held === 'number') {
                        this.memo.dropBaseline(personKey, held + 1)
                    } else {
                        this.memo.raiseFloorPastAppliedWrite(personKey)
                    }
                }
            }
        }
    }

    /**
     * Re-resolves a lane's distinct id after its person vanished and writes
     * the snapshot to the survivor.
     *
     * Answers 'written' once the survivor takes them, 'size_violation' when
     * the leader rejects a unit at the properties ceiling, and 'gone' when
     * the id resolves to nobody, the one outcome the caller discards on. The
     * other dead ends throw instead: an id still naming the vanished person
     * is identity lag, and a survivor that vanishes restarts the loop.
     */
    private async redirectToSurvivor(
        entry: OpsLaneEntry,
        progress: { remaining: number },
        fenceDeadline: number,
        ownFence?: Promise<void>
    ): Promise<RedirectOutcome> {
        // Each pass re-resolves against the person the previous one failed to
        // write, so consecutive merges on one lineage converge rather than
        // dropping. Postgres loops its refresh for the same reason.
        //
        // A lane captured before its person was fenced can arrive mid-merge,
        // where writing would land pre-merge ops raw, so the repointed
        // resolution has to exist first. A flush-issued redirect waits for
        // it; a merge-issued one refuses, since it holds fences of its own.
        // `awaitFences` owns that split.
        // The caller's deadline covers every fence this redirect waits on,
        // opening wait and per-attempt alike.
        const ownKey = `${entry.teamId}:${entry.personId}`
        await this.awaitFences(ownKey, ownFence, fenceDeadline)
        let vanished = entry.personId
        // Fence waits and identity re-reads are bounded separately, because
        // they answer different questions and one counter would let a run of
        // fences spend the allowance the re-reads need.
        // The furthest leader version any of this redirect's writes reached,
        // carried across attempts and throws: it becomes the floor under the
        // survivor's dropped baseline, so a read issued before those writes
        // cannot refill the absence with the state they replaced.
        const surviving: { version?: number } = {}
        for (let attempt = 0; attempt < REDIRECT_MAX_ATTEMPTS; attempt++) {
            // The resolve sits inside the try because it is a network call
            // like the write: a transient identity failure has to put the
            // entry back rather than leave it claimed and unwritten.
            let survivorId: string | undefined
            try {
                const [resolved] = await this.repository.resolvePersonsByDistinctIds(
                    [{ teamId: entry.teamId, distinctId: entry.distinctId }],
                    CALLER_TAG
                )
                survivorId = resolved?.person?.id
                // The top-of-redirect fence check is one moment; a merge can
                // fence either person after it. Writing under a live fence
                // lands pre-merge ops after the saga's own writes, so a
                // fence found now sends this back through the same wait or
                // refusal, and the attempt restarts with a fresh resolve.
                const fencedKey = [
                    `${entry.teamId}:${vanished}`,
                    ...(survivorId !== undefined ? [`${entry.teamId}:${survivorId}`] : []),
                ].find((key) => this.isHeldByOther(key, ownFence))
                if (fencedKey !== undefined) {
                    // Bounded in time, not in rounds: the shared fenceDeadline
                    // throws out of awaitFences on its own, so a second
                    // counted bound here was one mechanism answering a
                    // question the deadline already answers. The attempt is
                    // handed back so contention cannot spend the allowance
                    // meant for identity lag.
                    await this.awaitFences(fencedKey, ownFence, fenceDeadline)
                    attempt -= 1
                    continue
                }
                if (survivorId === undefined || survivorId === vanished) {
                    // Identity has not caught up with the merge the leader
                    // already applied. Refresh before concluding the person
                    // is gone, so lag does not read as a deletion and throw
                    // the ops away.
                    if (attempt < REDIRECT_MAX_ATTEMPTS - 1) {
                        await new Promise((resolve) =>
                            setTimeout(resolve, REDIRECT_REFRESH_INTERVAL_MS * (attempt + 1))
                        )
                        continue
                    }
                    if (survivorId === vanished) {
                        // Still naming the person the leader lost is the lag
                        // shape, not the deleted shape, since this read went
                        // to identity. Dropping would lose real writes
                        // whenever lag outruns the refresh allowance.
                        personhogStoreFlushCounter.inc({ outcome: 'redirect_lagged' })
                        throw new CountedRedirectError(
                            `identity still resolves ${entry.distinctId} to vanished person ` +
                                `${vanished} in team ${entry.teamId}; failing the flush rather than dropping`
                        )
                    }
                    // Identity resolves the id to nobody, so the memo's edge
                    // and the dead person's baseline are both answers this
                    // batch can no longer stand behind. Its siblings heal by
                    // repointing; there is nobody to repoint to here, so the
                    // id goes back to identity on its next event rather than
                    // folding onto the dead person and paying this again.
                    this.memo.releaseResolution(`${entry.teamId}:${entry.distinctId}`)
                    // Stamped like every other removal: a read already on
                    // the wire for this id or this person would otherwise
                    // reinstall the dead answer after the release, and the
                    // null-record guard would then refuse identity's
                    // truthful absence for the rest of the batch.
                    this.memo.bumpId(`${entry.teamId}:${entry.distinctId}`)
                    personhogStoreDeathStampCounter.inc({ site: 'redirect_gone' })
                    this.memo.markDestroyed(`${entry.teamId}:${entry.personId}`)
                    // Only the lane's own person needs dropping here. Every
                    // other person a chain of merges walked through was
                    // dropped as it was proved gone, which is also where
                    // `vanished` advanced to it.
                    this.memo.dropBaseline(`${entry.teamId}:${entry.personId}`)
                    return 'gone'
                }
                // Registered before the write goes on the wire. The recheck
                // above and this registration are one synchronous block, as
                // are a merge's fence-install and registry check, so either
                // the merge sees this redirect or this attempt saw the fence.
                // Otherwise a merge fencing the survivor mid-RPC could land
                // its writes first and have these older ops overwrite them.
                const survivorKey = `${entry.teamId}:${survivorId}`
                let settleRedirect: () => void = () => {}
                const redirecting = new Promise<void>((resolve) => {
                    settleRedirect = resolve
                })
                let registered = this.redirectsInFlight.get(survivorKey)
                if (!registered) {
                    registered = new Set()
                    this.redirectsInFlight.set(survivorKey, registered)
                }
                registered.add(redirecting)
                try {
                    // The person was merged away before this lane could be
                    // written, which another pod can cause because ingestion
                    // partitions by distinct id and personhog by person.
                    //
                    // The ops travel as they stand, deletions included, as
                    // Postgres carries its pending sets and unsets across and
                    // retries unchanged. Weakening them would diverge from
                    // that backend and discard a deletion the customer asked
                    // for.
                    await this.writeSegments(entry, survivorId, progress, surviving)
                } finally {
                    settleRedirect()
                    registered.delete(redirecting)
                    if (registered.size === 0 && this.redirectsInFlight.get(survivorKey) === registered) {
                        this.redirectsInFlight.delete(survivorKey)
                    }
                }
                // The id belongs to the survivor now. Healing the memo stops
                // every later event on this id from folding onto the dead
                // person and paying this path again — the same repoint the
                // Postgres cache performs on this exact signal.
                this.memo.repointResolution(`${entry.teamId}:${entry.distinctId}`, `${entry.teamId}:${survivorId}`)
                // Stamped like every other removal: without the bump, a read
                // of this id already on the wire passes its moved check and
                // reinstalls the dead edge over the repoint, and without the
                // mark a read answering the dead person refills its
                // baseline. Both heal through the redirect, but only after
                // folding events onto the corpse again.
                this.memo.bumpId(`${entry.teamId}:${entry.distinctId}`)
                personhogStoreDeathStampCounter.inc({ site: 'redirect_written' })
                this.memo.markDestroyed(`${entry.teamId}:${entry.personId}`)
                // These ops just landed on the survivor, and its baseline
                // answers for its own lane, which cannot know about them. The
                // leader can answer the merged document; this batch cannot
                // rebuild it, since the two lanes' unwritten ops have no
                // defined order between them. So drop it and re-read rather
                // than reconstruct — unless the survivor's own lane wrote
                // concurrently and installed a document past these writes,
                // which already contains them.
                this.memo.dropBaselineBehindWrites(`${entry.teamId}:${survivorId}`, surviving.version)
                return 'written'
            } catch (error) {
                if (error instanceof NoRowsUpdatedError) {
                    // The write proved this survivor gone, which is a death
                    // signal like any other: the mark drops its baseline and
                    // refuses reinstalls, or a concurrently installed
                    // document would keep serving the dead person. The
                    // behind-writes drop still runs for its floor, which the
                    // mark alone does not raise past the landed segments.
                    if (survivorId !== undefined) {
                        personhogStoreDeathStampCounter.inc({ site: 'redirect_vanished' })
                        this.memo.markDestroyed(`${entry.teamId}:${survivorId}`)
                        this.memo.dropBaselineBehindWrites(`${entry.teamId}:${survivorId}`, surviving.version)
                    }
                    // The person this pass resolved is gone too; the next pass
                    // must not settle for it again.
                    vanished = survivorId ?? vanished
                    continue
                }
                if (error instanceof PersonhogPropertiesSizeError) {
                    // The write failed but the resolve did not: this pass
                    // proved the person is gone and named the survivor, so
                    // the id is healed either way. Without this a rejection
                    // on the snapshot's last unit ends the loop with the
                    // edge still pointing at the dead person, and every
                    // later event in the batch pays the redirect again.
                    if (survivorId !== undefined) {
                        this.memo.repointResolution(
                            `${entry.teamId}:${entry.distinctId}`,
                            `${entry.teamId}:${survivorId}`
                        )
                    }
                    // Earlier segments may have landed before the refusal,
                    // leaving the survivor's baseline behind by those. It
                    // belongs to another lane, so nothing else here will
                    // correct it.
                    if (survivorId !== undefined) {
                        this.memo.dropBaselineBehindWrites(`${entry.teamId}:${survivorId}`, surviving.version)
                    }
                    // Logged here rather than at the caller, which has only
                    // the lane's own person, the one this redirect just
                    // proved is gone. The survivor is the person that
                    // refused, and it is named only in this scope.
                    logger.warn('🤔', 'leader refused a redirected write on properties size', {
                        team_id: entry.teamId,
                        person_id: survivorId,
                        distinct_id: entry.distinctId,
                    })
                    return 'size_violation'
                }
                throw error
            }
        }
        // Every attempt lost its race. The segments are still in the entry,
        // so failing here retries them on the batch's redelivery rather than
        // discarding writes the batch never acked.
        personhogStoreFlushCounter.inc({ outcome: 'redirect_exhausted' })
        throw new CountedRedirectError(
            `person ${entry.personId} in team ${entry.teamId} merged away ${REDIRECT_MAX_ATTEMPTS} times during redirect`
        )
    }

    /**
     * Reconciles the batch view against the persons a merge destroyed,
     * matching what the Postgres store does when it deletes a source:
     * clear the person and every distinct id that mapped to it.
     *
     * Two keys, because neither alone suffices. Reported person ids reach
     * ids the request never named, but a server predating the field reports
     * none; the named source distinct ids are always present and resolve
     * through the memo. Using both degrades to the older behavior rather
     * than to nothing.
     *
     * Ops still buffered for a destroyed person are kept, whether the
     * evidence is authoritative or a belief. Their next write meets the
     * tombstone and redirects to the survivor, which is what the reference
     * backend does with them too: its merge folds a source's pending
     * properties into the survivor before deleting the row.
     */
    private reconcileMergedPersons(
        teamId: number,
        destroyed: DestroyedSource[],
        survivorKey: string | undefined,
        batchId: number
    ): void {
        // Two classes, because the evidence differs. A server-named person
        // id is authoritative: that person is gone, its ids belong to the
        // survivor, its baseline and its buffered ops must go. A key
        // inferred from the memo is only as good as the memo, since a
        // replayed verdict or a merge on another pod can make it name a live
        // person, so those only release resolutions.
        const authoritative = new Set<string>()
        const inferred = new Set<string>()
        for (const { personKey, distinctKey, beliefKey } of destroyed) {
            if (personKey !== undefined) {
                authoritative.add(personKey)
            }
            const resolved = this.memo.resolutionOf(distinctKey)
            if (resolved != null) {
                inferred.add(resolved)
            }
            // The belief predates the merge's own resolve, which has already
            // rewritten this edge; without the captured copy, a lane folded
            // under the stale belief would go unclaimed.
            if (beliefKey !== undefined) {
                inferred.add(beliefKey)
            }
        }
        // The saga answers noop_same_person for same-person pairs, so the
        // survivor is never a destroyed source of its own merge; a memo
        // edge that says otherwise is stale (a replayed verdict whose
        // source id was already repointed) and claims nothing.
        if (survivorKey !== undefined) {
            authoritative.delete(survivorKey)
            inferred.delete(survivorKey)
        }
        // Every merged source's id, bumped even when the memo has never
        // seen it — a first-touch read has no edge for the loop further down
        // to find. Attached and same-person ids are deliberately not here:
        // their pre-merge reads answer null (an attach means the id was
        // unresolved until this merge), and the null-record guard already
        // refuses to downgrade the live mapping the caller writes, so a bump
        // would only add declines for reads the guard covers.
        for (const source of destroyed) {
            this.memo.bumpId(source.distinctKey)
        }
        if (authoritative.size === 0 && inferred.size === 0) {
            return
        }
        // A lane still holding ops for a person this merge destroyed is left
        // to write. Its next flush meets the tombstone and redirects to the
        // survivor, which is the mechanism that exists for exactly this.
        //
        // The reference backend keeps those ops too: its merge reads each
        // source through the cache that holds them, folds their properties
        // into the survivor, and only then deletes the row and clears the
        // entry. Discarding here would drop writes Postgres carries across,
        // and unlike the redirect it cannot be undone. Every way a lane can
        // still be pending at this point — a person born after the fence set
        // was computed, one whose id the merge never named, or one the saga
        // itself was holding when the pre-merge drain ran — is a lane whose
        // ops nothing else will write.
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
                if (survivorKey !== undefined && !this.memo.isDestroyed(survivorKey)) {
                    // Every id of a destroyed person belongs to the survivor,
                    // including ones this request never named; leaving them
                    // unresolved would send a resuming fold back to the dead
                    // person. Whether these edges serve the update class is
                    // the survivor baseline's own provenance to answer.
                    this.memo.recordResolution(batchId, key, survivorKey)
                } else {
                    this.memo.releaseResolution(key)
                }
                this.memo.bumpId(key)
                cleared++
            } else if (inferred.has(personKey)) {
                this.memo.releaseResolution(key)
                this.memo.bumpId(key)
                cleared++
            }
        }
        personhogStoreMergeCacheCounter.inc({ action: 'resolution_cleared' }, cleared)
        for (const personKey of authoritative) {
            // The person no longer exists, so its baseline goes whatever
            // still names it; the ids were just repointed or released.
            this.memo.deletePerson(personKey)
            // Marked as well as deleted: a read still on the wire that
            // answers this person has to be able to tell, and its id may
            // never have been named by this merge.
            personhogStoreDeathStampCounter.inc({ site: 'merge_verdict' })
            this.memo.markDestroyed(personKey)
        }
        if (stranded > 0) {
            logger.info('merge destroyed a person still holding folded ops; the flush redirects them', {
                team_id: teamId,
                segments: stranded,
            })
        }
    }

    /**
     * A failed merge call may still have destroyed persons this batch cached,
     * and which ones is unknowable with no verdict, so the team's resolutions
     * are dropped and re-resolve on next access.
     *
     * Documents are dropped only for persons holding no folded ops. One with
     * a pending lane behind it is the batch's own read-your-write view, so
     * dropping it would hide earlier updates from this batch's later events.
     */
    private invalidateTeamAfterFailedMerge(teamId: number): void {
        const cleared = this.memo.invalidateTeam(teamId)
        personhogStoreMergeCacheCounter.inc({ action: 'invalidated_after_failure' }, cleared)
    }

    /**
     * Frees a completed batch's memos and drops its references to shared
     * entries, as the Postgres store does after flush. Entries are
     * reference-counted so one batch finishing cannot evict ops another is
     * still folding into, and an entry still holding unwritten ops when its
     * last reference goes is deferred rather than evicted.
     */
    releaseBatch(batchId: number): void {
        // Any prefetch still on the wire for this batch answers into nothing
        // from here on.
        this.prefetchingBatches.delete(batchId)
        // Entries first: a baseline outlives its resolutions only while a
        // lane still holds ops behind it, so the distinct-key release below
        // has to see the entry map in its final state to make that call.
        const keys = this.batchEntryKeys.get(batchId)
        this.batchEntryKeys.delete(batchId)
        for (const personKey of keys ?? []) {
            if (this.entryHeldByAnyBatch(personKey)) {
                continue
            }
            const entry = this.entries.get(personKey)
            if (entry && entry.segments.length > 0) {
                // Evicting now would discard the ops. The entry stays until
                // its write drains it, which retires it through the same
                // refcount check.
                continue
            }
            this.retireEntry(personKey)
        }
        this.memo.releaseBatch(batchId)
        personhogStoreDestroyedMarksGauge.set(this.memo.destroyedCount())
    }

    /**
     * Releases a batch, discarding the unwritten segments the batch alone
     * was keeping: the shadow valve. A shadow flush failure cannot fail
     * the batch, so the authoritative backend acks and releases while
     * these lanes still hold ops, and keeping them would grow without
     * bound under a sustained personhog outage — the one shadow fault
     * that could take the authoritative process down. What is shed is
     * shadow fidelity, counted; the data's authority is the other
     * backend. Segments a still-open batch also references stay for that
     * batch's flush, and an in-flight lane keeps its claim, since its
     * write settles it either way.
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
                // The write owns the lane; zeroing its segments under it
                // would corrupt the pass. The flag hands the shed to the
                // write's settle instead, where a success drains normally
                // and a failure sheds what nothing references.
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
        personhogStoreDestroyedMarksGauge.set(this.memo.destroyedCount())
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
     * Whether any open batch still names this person's entry. A scan rather
     * than a maintained counter: `has` is constant time and batches number in
     * the handful, while a counter that can drift is a bug class for nothing.
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
        // Matching the Postgres store: lanes still holding ops at shutdown
        // mean the drain order is wrong somewhere, and that has to be loud —
        // the data itself is redelivery-safe, the bug is not.
        //
        // Counted by unwritten ops rather than by entry, because a drained
        // entry a batch has not released yet holds nothing and is not the
        // fault this is looking for.
        const unwritten = [...this.entries.values()].filter((entry) => entry.segments.length > 0).length
        if (unwritten > 0) {
            return Promise.reject(
                new Error(`PersonhogPersonsStore shut down with ${unwritten} lanes holding unwritten ops`)
            )
        }
        return Promise.resolve()
    }
}
