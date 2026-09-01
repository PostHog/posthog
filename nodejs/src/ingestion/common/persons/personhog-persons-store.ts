import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'
import pLimit from 'p-limit'
import { Counter, Gauge } from 'prom-client'

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
    help: 'Lifecycle-fence and in-flight-lane encounters on merge-side drain writes, by outcome',
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
 * How many reads a fold spends on a distinct id whose edge names a person
 * the caller does not hold. One read normally settles the answer into the
 * memo, so two consecutive merge overtakes is already pathological and the
 * third gives up rather than reading against a moving memo forever.
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
const FLUSH_MAX_WAIT_ROUNDS = 3
const FLUSH_WAIT_ROUND_MS = 1_000

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
     * Set while a flush is writing this entry's leading segments. Folds
     * arriving meanwhile start a new segment.
     */
    inFlight?: boolean
    /**
     * Settles when the current direct write finishes, so a merge that
     * fenced can await a write already on the wire before the saga applies
     * the merge event's own $set. Redirects are excluded because they wait
     * on the merge's fence.
     */
    directWriteSettled?: Promise<void>
    /** Resolves `directWriteSettled`; armed with it at claim time. */
    settleWrite?: () => void
    /**
     * Set when a shadow-mode release abandoned this entry while its write
     * was in flight. A failed write would otherwise leave an ownerless
     * entry no later abandon can reach, so the settle sheds it once
     * nothing references it.
     */
    abandoned?: boolean
}

/**
 * The personhog person store: resolution and creation through the identity
 * service (where person uuids derive from team_id:distinct_id, making the
 * uuid argument to createPerson advisory), person state through the
 * leader's strong reads, and property updates buffered as per-person lanes
 * of folded ops that flush writes one call per segment. Unlike the
 * Postgres store it writes ops as stated rather than refining them against
 * a fetched snapshot, so it needs no version-race machinery.
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
     * Redirects in flight, keyed by the person being written TO; the lane
     * itself sits under its vanished person's key, so a merge draining the
     * survivor needs this registry to wait it out. Set-valued because one
     * pass can redirect several lanes to one survivor.
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
        // pLimit throws on a value below 1 or a non-integer, and it is
        // built only after lanes are claimed for a write, which would leave
        // them marked in flight with nothing left to clear the mark.
        // Startup is the only place this can fail usefully.
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
        // A document below the standing floor is provably stale, and
        // handing it to the caller would let the fold suppress a genuine
        // change as no-change. Re-read bounded; on exhaustion fail the
        // batch rather than classify against it.
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
                // A null from the leader means the person was deleted or
                // merged away, and this read is the one death signal this
                // pod gets for a merge on another pod. The marks and id
                // bumps keep the dead answer out of the memo (the flush's
                // destroyed-person rescue redirects any folded ops to the
                // survivor); the caller still gets the identity answer.
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
        // Extras are never memoized: `created` speaks only for the primary,
        // and the service can leave a live conflicting extra mapped to its
        // existing person, so an edge recorded here could name a person the
        // service never mapped that id to. Extras resolve on first touch.
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
        // A merge can destroy the person between this resolve and the
        // lane's flush; the tombstone redirect then carries the ops to the
        // survivor, which is where a racing write lands under Postgres too.
        const target = await this.personNow(person, distinctId, batchId)
        return this.foldEventOps(target, ops, distinctId, batchId)
    }

    /**
     * Whether any merge but the caller's own holds this person. Avoids
     * building the holder list, because every fold asks and almost every
     * answer is no.
     */
    /**
     * The person this distinct id belongs to now, because a merge may have
     * destroyed the copy the caller resolved earlier, and folding onto that
     * would repoint the id back at the dead person and hand every later
     * event a pre-merge view. The answer always leaves through the memo,
     * never straight out of a read, so a merge completing inside the read's
     * await cannot hand back a person it has already destroyed.
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
            // A miss above answers identity and document at once. An edge
            // naming somebody other than the caller's person is the newer
            // truth, so the document has to be read rather than folded
            // onto, which is what makes dropping a baseline safe.
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
        // A first touch arrives with no baseline recorded, and the lane
        // about to hold ops is worthless without a document to replay them
        // over. Seeded only while the lane is empty: once a lane exists the
        // caller holds a view this store composed, and seeding from it
        // would replay ops it already contains.
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
        // resolve moves any edges: the drain covers what this pod BELIEVES
        // as well as what identity says, or a lane keyed on a stale belief
        // misses the fold.
        const memoOf = (distinctId: string) => this.memo.resolutionOf(`${request.teamId}:${distinctId}`)
        const memoSourceKeys = request.sources.map((source) => memoOf(source.distinctId))
        const memoTargetKey = memoOf(request.targetDistinctId)
        const fresh = await this.resolveForDrain(
            request.teamId,
            [request.targetDistinctId, ...request.sources.map((source) => source.distinctId)],
            batchId
        )
        // A source may name two persons, the memo's belief and identity's
        // answer, and both drain.
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
        // Claims arm their settle promise, so a writer already on the wire
        // is visible here even before it reaches its concurrency slot;
        // waiting lets the drain capture its lane instead of skipping it.
        const inFlightWrites = [
            ...personKeys.map((personKey) => this.entries.get(personKey)?.directWriteSettled),
            ...personKeys.flatMap((personKey) => [...(this.redirectsInFlight.get(personKey) ?? [])]),
        ].filter((settled): settled is Promise<void> => settled !== undefined)
        if (inFlightWrites.length > 0) {
            await Promise.all(inFlightWrites)
        }
        // Best-effort: a lane the drain cannot write right now (bounced on
        // a leader fence, or claimed by a redirect) lands after the merge
        // through the tombstone redirect instead of inside the fold.
        await this.writeLanesBeforeMerge(personKeys)
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
    }

    /**
     * One batched identity resolve of a merge's named ids, answering
     * `distinctId -> personKey`. Results are recorded as checking-class
     * reads, so reconcile's memo fallback sees them too.
     */
    private async resolveForDrain(
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
            // the fold; a memo fallback would leave unseen persons unheld,
            // their buffered ops landing after the fold unordered. Wrapped
            // because an unwrapped error reaches the merge service's
            // catch-all, which would ack the event with the merge lost.
            personhogStoreMergeCacheCounter.inc({ action: 'drain_resolve_failed' })
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
    private async writeLanesBeforeMerge(personKeys: string[]): Promise<void> {
        const captured: CapturedLane[] = []
        // Every named person's lane, whichever distinct id opened it.
        // Filtering by the merge's named ids would drop properties Postgres
        // keeps, since the reference backend's cache reaches a person's
        // pending update through any of its ids.
        for (const personKey of personKeys) {
            const entry = this.entries.get(personKey)
            if (!entry || entry.segments.length === 0) {
                continue
            }
            // A redirect owns the lane; its ops land on the survivor after
            // the merge rather than inside the fold.
            if (entry.inFlight) {
                personhogStoreFenceCounter.inc({ outcome: 'premerge_lane_in_flight' })
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
            // A lifecycle op holds the person, often this request's own op
            // from an earlier interrupted delivery. Calling the saga is
            // what settles either case: an own op resumes under its op id,
            // a foreign one answers an unsettled conflict the batch
            // redelivers behind, and the sweeper re-drives any abandoned
            // holder. The lane's ops stay and land through the redirect.
            if (error instanceof PersonhogFencedError) {
                personhogStoreFenceCounter.inc({ outcome: 'premerge_lane_fenced' })
                continue
            }
            // Any other failure leaves the merge unattempted. The typed
            // wrapper is what makes the merge service fail the batch;
            // unwrapped, a generic catch would ack and drop the merge.
            throw new PersonMergeCallFailedError(
                `personhog pre-merge write failed: ${error instanceof Error ? error.message : String(error)}`,
                error
            )
        }
    }

    private async runMerge(
        request: MergePersonsRequest,
        batchId: number,
        beliefs: Map<string, string>
    ): Promise<MergePersonsResult> {
        // Verdicts are recorded durably against the op id, so a
        // skipped_conflict retry salts a counter suffix into the derivation
        // for a fresh look; it cannot double-merge, because a conflict
        // verdict proves the aborted op destroyed nothing and a fresh op
        // against an already merged graph settles as noop_same_person.
        // Retrying is for a single source only, because a fold's fresh op
        // id would re-run the sources that did settle.
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
                        // The saga refuses a negative created_at, and events
                        // stamped before 1970 exist, so the floor is applied
                        // where that constraint lives rather than in the
                        // shared request the Postgres backend also reads.
                        createdAtMs: Math.max(0, request.createdAtMs),
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
                // The replay guard's refusal is deterministic (the op id
                // names a different recorded merge) and pre-durable, so it
                // propagates raw to be acked loudly rather than wedging
                // the partition on one duplicated event uuid. Keyed on the
                // refusal's reason slug rather than the status code,
                // because a semantic refusal can also arrive from a later
                // saga step, where skipping the invalidation below would
                // be wrong.
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
                // No verdict arrived, so an ack could lose the merge; the
                // typed wrapper makes the merge service fail the batch, and
                // redelivery replays the saga idempotently. Only the call
                // is wrapped, so a bug in post-verdict processing surfaces
                // as itself.
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
        // A fold that skipped any source aborts, after the reconcile above
        // has taken account of the sources that did merge: acking the
        // skipped sources with nothing behind them is a durability decision
        // the all-or-nothing Postgres fold never makes, so each gets its
        // own sequential decision on redelivery. Retrying the whole fold
        // under a fresh op id is not an option either, since it would
        // re-run the sources that settled.
        if (!singleSource) {
            const overLimit = result.results.some((source) => source.outcome === 'skipped_move_limit')
            const conflicted = result.results.some((source) => source.outcome === 'skipped_conflict')
            const refused = result.results.some((source) => source.outcome === 'skipped_refused')
            // Abort-ness is reconstructed from verdict names, so the net
            // has to catch every aborted shape. An error verdict with no
            // merged source alongside it can only be an abort, because
            // completion implies at least one source folded.
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
            // Update authority enters the memo only through leader reads
            // and own-write answers, never through a response document,
            // whose replayed or identity-lagged state could suppress a
            // genuinely new value as no-change. So the survivor's version
            // only floors the key (state the leader provably passed), and
            // one leader read supplies the document the batch folds
            // against.
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
                // The verdict is durable and reconciled; only the refresh
                // is lost, so installing nothing degrades to read
                // amplification while throwing would fail a batch whose
                // merge committed. The caller still folds against the
                // response document, which is safe because the service
                // already applied the merge's own ops durably.
                personhogStoreMergeCacheCounter.inc({ action: 'survivor_refresh_failed' })
                logger.warn('🤔', 'merge survivor refresh failed; batch proceeds without a leader document', {
                    team_id: request.teamId,
                    person_id: result.survivor.id,
                    error: String(error),
                })
                return {
                    survivor: result.survivor,
                    results: result.results,
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
                // verdicted to this pod; installing nothing degrades to
                // read amplification, and the caller's fold stays safe
                // because its ops are durable server-side. A mid-read
                // watermark sweep trips this too, so the counter reads as
                // an upper bound on invalidations.
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
        }
    }

    /**
     * Whether a lane still holds ops no write has taken, which an existing
     * entry alone does not prove: an entry outlives its segments. A drained
     * lane holds nothing a fetch could be missing, so it must not go on
     * winning against one.
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
     * A direct diff update mapped onto the leader's folded-update RPC;
     * fields of `otherUpdates` with no RPC counterpart fail loudly rather
     * than dropping silently. Deliberately outside the local fence and lane
     * protocol, which orders buffered work: this path buffers nothing, and
     * a race with a remote merge is stopped by the leader's own fence,
     * failing the batch to redelivery.
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
                forceUpdate: forceUpdate ?? false,
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
        if (!read.moved(`${person.team_id}:${_distinctId}`, personKey)) {
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
     * Writes the batch's folded lanes to the leader, one call per segment;
     * nothing publishes, because the leader's changelog is this backend's
     * person feed. A missing person redirects to whatever its distinct id
     * resolves to now, a person genuinely gone and a size rejection are
     * counted and dropped since neither can succeed on retry, and anything
     * else fails the flush. Passes serialize, snapshotting each lane's
     * segment count so a partial failure keeps what it did not attempt,
     * and a lane with no update-worthy change is suppressed as Postgres
     * does.
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
        // A pass records the segment count, marks the lane in flight, and
        // truncates exactly that many on success, so a failure leaves the
        // entry as it was with no claim to strand. No await in this block:
        // the snapshot is atomic.
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
        // A drained entry no batch still references was held open only to
        // protect its unwritten ops; now it can go. Identity-guarded: a
        // stale finalizer (an old write settling after the entry was retired
        // and recreated) must not retire the new entry's unwritten ops.
        if (!this.entryHeldByAnyBatch(personKey) && this.entries.get(personKey) === entry) {
            this.retireEntry(personKey)
        }
    }

    private async writeEntry(personKey: string, entry: OpsLaneEntry, segments: number): Promise<void> {
        try {
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
            while (progress.remaining > 0) {
                try {
                    if (viaRedirect) {
                        const outcome = await this.redirectToSurvivor(entry, progress)
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
                        // Settled before the redirect phase because the
                        // redirect waits on merge fences and a merge waiting
                        // on this promise would close a cycle; a size-drop
                        // resume stays pending, since that write is still a
                        // direct one the merge must order behind.
                        entry.settleWrite?.()
                        entry.settleWrite = undefined
                        entry.directWriteSettled = undefined
                        viaRedirect = true
                        continue
                    }
                    if (error instanceof PersonhogPropertiesSizeError) {
                        // The rejected segment can never succeed, so it goes
                        // and the loop writes the remainder now, unlike
                        // Postgres, where one oversized row aborts its whole
                        // batch statement. The customer-facing warning comes
                        // from the leader, which emits
                        // PersonPropertiesSizeViolation but throttles it to
                        // one per team per hour, so the log line is what
                        // attributes the individual discard.
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

    /**
     * A service document with a lane's unsent ops applied on top, which is
     * what a read of that person should answer. Built from the same
     * refine-and-apply pair the Postgres backend writes through rather than
     * a second reading of the leader's rules, and outcomes stay unrecorded
     * because these events were counted when they were folded.
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
                forceUpdate: ops.shouldForceUpdate,
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
            // Installing the answered document keeps the baseline tracking
            // the leader, because a read issued before this write and
            // delivered after it carries the same version as the baseline
            // and nothing could tell the two apart. Only where the lane
            // owns the person: a redirect writes to a survivor whose
            // baseline answers for another lane, and the redirect drops
            // that baseline once it is done.
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
     * the snapshot to the survivor, answering 'written', 'size_violation',
     * or 'gone', the one outcome the caller discards on. The other dead
     * ends throw instead: an id still naming the vanished person is
     * identity lag, and a survivor that vanishes restarts the loop.
     */
    private async redirectToSurvivor(entry: OpsLaneEntry, progress: { remaining: number }): Promise<RedirectOutcome> {
        // Each pass re-resolves against the person the previous one failed
        // to write, so consecutive merges on one lineage converge rather
        // than dropping. A write landing under a live leader fence bounces
        // there and the batch redelivers behind the holder.
        let vanished = entry.personId
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
                // Registered before the write goes on the wire, in one
                // synchronous block with the recheck above, so either a
                // merge sees this redirect or this attempt saw the fence.
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
                    // partitions by distinct id and personhog by person. The
                    // ops travel as they stand, deletions included, because
                    // weakening them would diverge from Postgres and discard
                    // a deletion the customer asked for.
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
                // These ops just landed on the survivor, whose baseline
                // answers for its own lane and cannot know about them, and
                // the two lanes' unwritten ops have no defined order to
                // rebuild from. So drop it and re-read, unless the
                // survivor's own lane concurrently installed a document
                // past these writes, which already contains them.
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
     * clearing each person and every distinct id that mapped to it; both
     * reported person ids and named source distinct ids are used, because a
     * server predating the id field reports none and using both degrades to
     * the older behavior rather than to nothing. Ops still buffered for a
     * destroyed person are kept: their next write meets the tombstone and
     * redirects to the survivor, as the reference backend folds a source's
     * pending properties across before deleting the row.
     */
    private reconcileMergedPersons(
        teamId: number,
        destroyed: DestroyedSource[],
        survivorKey: string | undefined,
        batchId: number
    ): void {
        // A server-named person id is authoritative: that person is gone,
        // and its ids, baseline, and buffered ops go with it. A key
        // inferred from the memo is only as good as the memo (a replayed
        // verdict can make it name a live person), so those only release
        // resolutions.
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
        // A lane still holding ops for a person this merge destroyed is
        // left to write: its next flush meets the tombstone and redirects
        // to the survivor. Discarding here would drop writes the reference
        // backend carries across (it folds a source's pending properties
        // into the survivor before deleting the row), and unlike the
        // redirect it cannot be undone.
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
     * A failed merge call may still have destroyed persons this batch
     * cached, and which ones is unknowable with no verdict, so the team's
     * resolutions are dropped and re-resolve on next access. Documents are
     * dropped only for persons holding no folded ops, because a pending
     * lane's document is the batch's own read-your-write view.
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
     * the batch, so keeping these lanes would grow without bound under a
     * sustained personhog outage (the one shadow fault that could take
     * the authoritative process down); what is shed is counted shadow
     * fidelity, while segments a still-open batch references stay and an
     * in-flight lane keeps its claim.
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
