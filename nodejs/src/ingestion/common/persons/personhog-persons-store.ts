import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'
import pLimit from 'p-limit'
import { Counter } from 'prom-client'

import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogPropertiesSizeError } from '~/common/personhog/persons'
import { PersonMessage } from '~/common/persons/person-message'
import { isDistinctIdIllegal } from '~/common/persons/person-utils'
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
import { mergeOpIdFromRequest, mergePayloadFingerprint } from './person-uuid'
import { PersonhogPersonMemo } from './personhog-person-memo'
import { FlushResult, MergePersonsRequest, MergePersonsResult, PersonsStore } from './persons-store'
import { BatchBoundPersonsStore, PersonsStoreForBatch } from './persons-store-for-batch'

export const personhogStoreFlushCounter = new Counter({
    name: 'personhog_store_flush_ops_total',
    help: 'Folded person updates flushed to the personhog leader, by outcome',
    labelNames: ['outcome'],
})

export const personhogStoreMergeCacheCounter = new Counter({
    name: 'personhog_store_merge_cache_total',
    help: 'Batch-cache entries a saga merge invalidated, by action',
    labelNames: ['action'],
})

export const personhogStoreFenceCounter = new Counter({
    name: 'personhog_store_fence_waits_total',
    help: 'Folds that waited on a person held by an in-flight merge, by how the wait ended',
    labelNames: ['outcome'],
})

export const personhogStoreCarriedSkippedCounter = new Counter({
    name: 'personhog_store_carried_skipped_total',
    help: 'Lanes left out of a merge request, by why the carry could not take them',
    labelNames: ['reason'],
})

export const personhogStoreCarriedCounter = new Counter({
    name: 'personhog_store_carried_operations_total',
    help: 'Buffered operation lanes sent inside a merge request, by whether the service applied them',
    labelNames: ['outcome'],
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
     * Bounds concurrent RPC fan-out (batch fetches and flush). Its own
     * knob on purpose: the Postgres store's identically named option
     * exists to avoid connection-pool starvation, a resource this store
     * does not hold.
     */
    maxConcurrentUpdates: number
    /**
     * When true, every property change triggers a person update in the
     * local projection, matching the Postgres store's option of the same
     * name. Wiring must hand both stores the same value or their
     * projections diverge by construction.
     */
    updateAllProperties: boolean
    /**
     * The saga's required per-source move guard in SYNC merge mode,
     * which has no client-side limit of its own. Sized so only
     * pathological persons reach it; a source over the limit comes back
     * skipped_move_limit and the merge-mode policy decides the event's
     * fate.
     */
    syncMergeMoveLimit: number
    /**
     * The per-call deadline on merge RPCs, from the same config the client
     * transport is built with. The fence budget derives from it, so the two
     * cannot drift apart; see FENCE_WAIT_SLACK_MS.
     */
    mergeRpcTimeoutMs: number
}

const DEFAULT_OPTIONS: PersonhogPersonsStoreOptions = {
    maxConcurrentUpdates: 10,
    updateAllProperties: false,
    syncMergeMoveLimit: 10_000,
    mergeRpcTimeoutMs: 3_000,
}

const CALLER_TAG = 'ingestion/personhog-store'

/** Every move limit the saga accepts is an integer of at least 1. */
function assertMoveLimit(source: string, limit: number): void {
    if (!Number.isInteger(limit) || limit < 1) {
        throw new Error(`${source} must be an integer >= 1, got ${limit}`)
    }
}

/**
 * SYNC carries no limit of its own, so it uses the store's. The other modes
 * carry the configured one, which `determineMergeMode` has already held to
 * the same contract at startup — validating again here would only throw
 * somewhere the error cannot usefully surface.
 */
function moveLimitFor(mergeMode: MergeMode, syncMergeMoveLimit: number): number {
    return mergeMode.type === 'SYNC' ? syncMergeMoveLimit : mergeMode.limit
}

/** The event name stamped on creation calls; per-event names are consumed at fold time. */
const CREATE_EVENT_NAME = '$create_person'

/** The event name stamped on direct diff updates, which carry no originating event. */
const DIRECT_UPDATE_EVENT_NAME = '$direct_update'

/**
 * A store verb with no personhog RPC behind it. The shadow gates the
 * events that reach these verbs off this store, so hitting one is a
 * wiring bug; it fails loudly instead of no-oping into silent
 * divergence.
 */
export class PersonhogPendingRpcError extends Error {
    constructor(method: string, needs: string) {
        super(`PersonhogPersonsStore.${method} has no personhog RPC: ${needs}`)
        this.name = 'PersonhogPendingRpcError'
    }
}

/**
 * Bounds the re-resolve loop so a lineage merging faster than the flush
 * can drain still terminates. Each pass costs one resolve plus one write.
 * Exhausting it throws rather than dropping, so the ops survive in the
 * batch's redelivery.
 */
const REDIRECT_MAX_ATTEMPTS = 5

/**
 * Headroom the fence budget carries over one merge RPC deadline, covering
 * the awaits that surround the call inside the fence: draining writes
 * already on the wire, and the merge's own resolve.
 *
 * The budget is deliberately sized for a merge making ONE attempt, not for
 * its whole retry sequence. A merge that retries is contending, and holding
 * every fold for that person across the full sequence would multiply into
 * the flush's own bounded rounds and risk stalling the poll loop past
 * Kafka's max.poll.interval.ms — losing the partition to preserve one
 * event's ordering. A retrying merge instead falls through to the timeout
 * path, which is safe: the fold proceeds, reconcile marks its lane, and the
 * redirect delivers the ops to the survivor with source precedence. What it
 * costs is that event's enrichment freshness, not its data.
 */
const FENCE_WAIT_SLACK_MS = 2_000

/** How many back-to-back merges a single fold will wait out before proceeding. */
const FENCE_MAX_CHAINED_WAITS = 3

/**
 * Pause between re-resolves when the identity service still answers with the
 * person the leader has already lost. The two are different stores and the
 * resolution reads the one that lags, so an answer that has not caught up
 * looks identical to a deleted person. Postgres re-reads the store it wrote
 * to, which makes its own answer authoritative; this one is not, so the
 * tolerance has to cover the lag rather than trust the first reply.
 *
 * Backs off, because a resolution still catching up is the case worth
 * waiting for and a person genuinely deleted costs the full budget once.
 */
const REDIRECT_REFRESH_INTERVAL_MS = 100

/**
 * How many wait-and-redirect rounds a flush spends on lanes parked behind
 * in-flight merges before failing the pass. Each round's fence waits are
 * themselves bounded, so the worst case is loud and finite rather than an
 * ack over unwritten ops.
 */
const FLUSH_MAX_MERGE_WAIT_ROUNDS = 3

type RedirectOutcome = 'written' | 'gone' | 'size_violation'

/** A redirect failure that already incremented its own flush outcome. */
class CountedRedirectError extends Error {}

/**
 * Matches the service's own cap. Exceeding it is INVALID_ARGUMENT, which
 * would fail a merge that has nothing wrong with it, so the surplus lanes
 * stay behind and write the ordinary way instead.
 */
const MAX_CARRIED_LANES = 32

/** The service's own distinct-id ceiling; over it the whole request is rejected. */
const MAX_CARRIED_DISTINCT_ID_LENGTH = 400

/** A source a merge destroyed, at its rank in the request's precedence order. */
interface DestroyedSource {
    rank: number
    /** Absent on a server that does not report the id. */
    personKey: string | undefined
    distinctKey: string
    /** The memo's pre-resolve belief for the id, when it had one. */
    beliefKey?: string
}

/** One lane's pending operations, sent inside a merge request. */
interface CarriedLane {
    entry: OpsLaneEntry
    /** The exact segment sent, so truncation cannot remove a different one. */
    ops: EventOps
}

interface OpsLaneEntry {
    teamId: number
    personId: string
    distinctId: string
    /**
     * Folded ops in arrival order. Almost always one segment; a new one
     * starts only when foldOps cannot represent the composition, and
     * flush writes segments sequentially so the leader refines between
     * them.
     */
    segments: EventOps[]
    /**
     * Whether any folded event triggers a person update against its
     * projection baseline, per the ignored-property rules. A lane that
     * never turns this on holds filtered-only noise, and flush
     * suppresses it — the same no-op classification the Postgres store
     * applies at its flush.
     */
    triggersUpdate: boolean
    /**
     * Set while a flush is writing this entry's leading segments. Folds
     * arriving meanwhile start a new segment rather than merging into one
     * already on the wire.
     */
    inFlight?: boolean
    /**
     * Settles when the current direct write attempt finishes (landed or
     * failed), before any redirect. A merge awaits this after fencing: a
     * write already on the wire must land before the saga applies the
     * merge event's own $set, or the older value silently overwrites the
     * newer. The redirect path is excluded because it waits on the merge's
     * fence — including it here would deadlock the two.
     */
    directWriteSettled?: Promise<void>
    /**
     * The segments that were already folded when a merge destroyed this
     * entry's person. Only those logically precede the merge, so only those
     * redirect with source precedence; anything folded afterwards is a later
     * write and keeps its own. Held by segment identity rather than by
     * count, so it stays accurate as segments write and shift away.
     */
    demoted?: Set<EventOps>
    /**
     * The demoting merge's source rank. A merge gives earlier sources
     * precedence over later ones and a demoted lane contributes $set_once,
     * which resolves first-wins, so demoted lanes must reach the survivor
     * in this order.
     */
    demoteRank?: number
}

/**
 * The personhog implementation of the person store: distinct-id
 * resolution and person creation through the identity service's
 * get-or-create, person state through the leader's strong reads, and
 * property updates as raw op folds written to the leader, which refines
 * them against authoritative state under the per-person lock.
 *
 * Where the Postgres store refines ops against a fetched snapshot before
 * writing, this store writes them as stated, so no version-race machinery
 * exists here. Fetches memoize per batch; folded ops accumulate per
 * (batch, person) and flush as one call per person.
 *
 * Person uuids derive deterministically from team_id:distinct_id on the
 * identity service; the uuid argument to createPerson is advisory and
 * the returned person carries the authoritative one.
 */
export class PersonhogPersonsStore implements PersonsStore {
    readonly backend = 'personhog' as const

    private options: PersonhogPersonsStoreOptions
    /**
     * Folded ops, one entry per person, keyed by `${teamId}:${personId}`
     * and shared by every batch that touched that person. One entry means
     * one writer: two batches holding the same person can no longer write
     * it concurrently and let an older value land last.
     */
    private entries: Map<string, OpsLaneEntry> = new Map()
    /** Person keys each open batch references, for the release refcount. */
    private batchEntryKeys: Map<number, Set<string>> = new Map()
    /**
     * The shared memo: resolutions, projections, read grades, and their
     * per-batch liveness. The predicate hands it the one lane fact it
     * needs — a person with folded, unwritten ops keeps its projection.
     */
    private memo: PersonhogPersonMemo = new PersonhogPersonMemo((personKey) => this.entries.has(personKey))
    /**
     * Persons held by an in-flight merge. A fold onto one waits for the
     * merge to settle and reconcile, so operations cannot accumulate behind
     * a request that has already been sent.
     */
    private fences: Map<string, Promise<void>> = new Map()
    /**
     * Redirects in flight, keyed by the person being written TO. A redirect's
     * lane sits under its vanished person's key, so a merge fencing the
     * survivor cannot find it through the entry map; this registry is what
     * lets the merge wait it out. Set-valued because one pass can redirect
     * several lanes to the same survivor concurrently, and the merge must
     * wait for all of them.
     */
    private redirectsInFlight: Map<string, Set<Promise<void>>> = new Map()
    /** Serializes flush passes; see flush(). */
    private flushChain: Promise<void> = Promise.resolve()
    /**
     * How long one fold waits for a merge holding its person: one merge RPC
     * deadline plus the slack around it. A merge that hangs must slow those
     * persons briefly, never stall ingestion for them, so the wait is
     * bounded and a timeout is counted rather than thrown.
     */
    private readonly fenceWaitMs: number

    constructor(
        private repository: PersonHogPersonWriteRepository,
        options?: Partial<PersonhogPersonsStoreOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
        // The saga rejects a move limit below 1 with INVALID_ARGUMENT, and a
        // non-integer survives config parsing only to throw a RangeError
        // inside BigInt() when the request is built. Either turns every merge
        // in the deployment into a failure, so they fail startup instead.
        assertMoveLimit('PERSONHOG_SYNC_MERGE_MOVE_LIMIT', this.options.syncMergeMoveLimit)
        if (!Number.isFinite(this.options.mergeRpcTimeoutMs) || this.options.mergeRpcTimeoutMs <= 0) {
            throw new Error(`PERSONHOG_TIMEOUT_MS must be a positive number, got ${this.options.mergeRpcTimeoutMs}`)
        }
        // Derived rather than fixed: a fence sized independently of the
        // deadline it covers stops covering it the moment either moves.
        this.fenceWaitMs = this.options.mergeRpcTimeoutMs + FENCE_WAIT_SLACK_MS
    }

    forBatch(batchId: number): PersonsStoreForBatch {
        return new BatchBoundPersonsStore(this, batchId)
    }

    /**
     * Checking reads resolve through identity (primary-backed) and use
     * the resolved person directly: writer-applied state is within this
     * read class's eventual contract, and it saves the leader hop.
     */
    async fetchForChecking(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const cached = this.memo.lookup(teamId, distinctId, 'checking')
        if (cached !== undefined) {
            return this.memo.snapshot(cached)
        }
        const issuedAt = this.memo.generation
        const [resolved] = await this.repository.resolvePersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        if (this.memo.generation !== issuedAt) {
            // A merge rewrote the memo mid-flight: this response may name a
            // person the merge destroyed, and installing it would overwrite
            // the survivor edge reconcile just recorded. The caller still
            // gets the answer; the memo keeps the merge's.
            return this.memo.snapshot(resolved?.person ?? null)
        }
        return this.memo.snapshot(
            this.memo.record(teamId, distinctId, resolved?.person ?? null, batchId, { grade: 'checking' })
        )
    }

    /**
     * Update reads split resolution from state: identity resolves the
     * distinct id on the primary, then the person's state comes from the
     * partition leader, which the primary lags by writer apply lag. The
     * projection this feeds enriches the batch's events, so the baseline
     * must be the leader's.
     */
    async fetchForUpdate(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const cached = this.memo.lookup(teamId, distinctId, 'update')
        if (cached !== undefined) {
            return this.memo.snapshot(cached)
        }
        const issuedAt = this.memo.generation
        const [resolved] = await this.repository.resolvePersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        if (!resolved?.person) {
            if (this.memo.generation !== issuedAt) {
                return null
            }
            return this.memo.snapshot(this.memo.record(teamId, distinctId, null, batchId, { grade: 'update' }))
        }
        // A null here means the person vanished between resolve and read
        // (merged or deleted mid-flight); record the resolution miss and
        // let the caller's create path re-resolve authoritatively.
        const person = await this.repository.fetchPersonById(teamId, resolved.person.id, CALLER_TAG)
        if (this.memo.generation !== issuedAt) {
            // A merge rewrote the memo mid-flight; hand back the read but
            // leave the memo with the merge's answer.
            return this.memo.snapshot(person)
        }
        return this.memo.snapshot(this.memo.record(teamId, distinctId, person, batchId, { grade: 'update' }))
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
        const issuedAt = this.memo.generation
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
        // Whether this person's state came through the leader, which is what
        // the update read class requires. Creation is leader-durable; the
        // found branch earns it by paying the leader read below. Carried to
        // the resolution record rather than granted before it, because
        // recording an edge starts it at the checking grade and would drop a
        // grant made beforehand.
        let leaderBacked = created
        if (!created) {
            // The found branch answers identity's document, which the leader
            // leads by writer apply lag. This document becomes the baseline
            // the caller's ops fold against, and a lagged baseline can make
            // a genuinely new $set classify as no-change and be suppressed —
            // so the found branch pays the same leader read the update fetch
            // path does. A miss (merged away again mid-flight) keeps the
            // identity document; the caller's own retry loop re-resolves.
            const leaderDoc = await this.repository.fetchPersonById(teamId, person.id, CALLER_TAG)
            person = leaderDoc ?? person
            leaderBacked = leaderDoc != null
        }
        if (this.memo.generation !== issuedAt) {
            // A merge rewrote the memo while this call was in flight; the
            // response may describe a person the merge destroyed. The caller
            // still gets it — installing it is what must not happen.
            return { success: true, person: this.memo.snapshot(person), messages: [], created }
        }
        const personKey = `${teamId}:${person.id}`
        this.memo.recordResolution(
            batchId,
            `${teamId}:${primaryDistinctId.distinctId}`,
            personKey,
            leaderBacked ? 'update' : 'checking'
        )
        if (created) {
            // Extras are mapped on the creation branch only: an extra that
            // already resolves elsewhere keeps its mapping, so memoizing it
            // here would invent an edge the service never made. Creation is
            // leader-durable, so every id it mapped serves the update class.
            for (const extra of extraDistinctIds ?? []) {
                this.memo.recordResolution(batchId, `${teamId}:${extra.distinctId}`, personKey, 'update')
            }
        }
        // A projection behind a lane carries this batch's own writes and
        // must not roll back to service state (the found branch can race a
        // fold under another distinct id of the same person).
        if (!this.entries.has(personKey) || !this.memo.hasProjection(personKey)) {
            this.memo.setProjection(personKey, person)
        }
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

        // Folding onto a person a merge is holding would put operations
        // behind a request already on the wire, where they would land after
        // the merge instead of taking part in it. The unfenced path keeps
        // its synchronous shape; only a held person pays for the wait.
        const fence = this.fences.get(`${person.team_id}:${person.id}`)
        if (fence) {
            return this.awaitFences(`${person.team_id}:${person.id}`, fence).then(() =>
                this.foldEventOps(this.personAfterFence(person, distinctId), ops, distinctId, batchId)
            )
        }
        return Promise.resolve(this.foldEventOps(person, ops, distinctId, batchId))
    }

    /**
     * Waits out the person's fence, and any fence installed behind it: a
     * release only proves that one merge settled, and an overlapping merge
     * may already hold the person, where folding would land mid-request and
     * be wrongly swept into its demotion. Bounded like the single wait, so
     * back-to-back merges delay a fold rather than starve it.
     */
    private async awaitFences(personKey: string, first: Promise<void>): Promise<void> {
        let current: Promise<void> | undefined = first
        for (let chained = 0; current && chained < FENCE_MAX_CHAINED_WAITS; chained++) {
            await this.awaitFence(personKey, current)
            const next = this.fences.get(personKey)
            current = next === current ? undefined : next
        }
        if (current) {
            personhogStoreFenceCounter.inc({ outcome: 'chain_exhausted' })
        }
    }

    /**
     * The person a fenced distinct id belongs to now that the merge has
     * settled. The caller resolved its person before the wait, so on a merge
     * that destroyed it the caller's copy names a person that no longer
     * exists; folding onto that would repoint the distinct id back at the
     * dead person and hand every later event a pre-merge projection.
     *
     * A successful merge repoints every id of a person it destroyed at
     * the survivor before releasing the fence, so the lookup is
     * authoritative here and costs no round trip, and a miss means the
     * merge left this id alone. A FAILED merge releases the team's
     * resolutions instead — the outcome is unknowable — so a miss there
     * falls back to the caller's person; if that person did die, the
     * marked lane and the redirect deliver the ops to the survivor anyway,
     * at the cost of stale enrichment until the flush.
     */
    private personAfterFence(person: InternalPerson, distinctId: string): InternalPerson {
        const resolved = this.memo.lookup(person.team_id, distinctId, 'checking')
        return resolved ?? person
    }

    private async awaitFence(personKey: string, fence: Promise<void>): Promise<void> {
        let timer: NodeJS.Timeout | undefined
        const expired = new Promise<'timeout'>((resolve) => {
            timer = setTimeout(() => resolve('timeout'), this.fenceWaitMs)
        })
        try {
            const outcome = await Promise.race([fence.then(() => 'released' as const), expired])
            personhogStoreFenceCounter.inc({ outcome })
            if (outcome === 'timeout') {
                logger.warn('🤔', 'fold proceeded past a merge fence that did not release in time', {
                    person_key: personKey,
                })
            }
        } finally {
            clearTimeout(timer)
        }
    }

    /**
     * Holds a set of persons for the duration of a merge and answers the
     * release. The release runs from a finally on every exit: a fence left
     * standing would make every later fold for those persons wait out the
     * full timeout.
     */
    private fencePersons(personKeys: string[]): () => void {
        let release: () => void = () => {}
        const fence = new Promise<void>((resolve) => {
            release = resolve
        })
        for (const personKey of personKeys) {
            this.fences.set(personKey, fence)
        }
        return () => {
            for (const personKey of personKeys) {
                if (this.fences.get(personKey) === fence) {
                    this.fences.delete(personKey)
                }
            }
            release()
        }
    }

    private foldEventOps(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string,
        batchId: number
    ): [InternalPerson, PersonMessage[]] {
        // A local projection for the caller: the same application the
        // Postgres backend would perform, so the processor returns a
        // sensible person. The leader's application at flush remains the
        // authoritative one for this backend.
        const refined = refineEventOps(ops, person.properties ?? {}, this.options.updateAllProperties, false)
        const [projected] = applyEventPropertyUpdates(refined, person)
        const scalarUpdates = computeOpsScalarUpdates(ops, projected)
        Object.assign(projected, scalarUpdates)
        // An event triggers an update when the refinement found a
        // non-filtered change against its baseline, or a scalar moved.
        // Filtered-only noise leaves it false, and a lane of nothing but
        // noise is suppressed at flush.
        const triggersUpdate =
            (refined.hasChanges && refined.hasNonFilteredChanges) || Object.keys(scalarUpdates).length > 0

        const personKey = `${person.team_id}:${person.id}`
        this.referenceEntry(batchId, personKey)
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
            // A flush writes a snapshot of the leading segments and truncates
            // exactly that many on success, so folding into one already on
            // the wire would either change the payload underneath it or lose
            // this event when the snapshot is dropped. A demote-marked
            // segment refuses folds for its own reason: foldOps returns a
            // new object, which would fall out of the marked set and weld
            // post-merge ops onto pre-merge ones — both then writing with
            // the wrong precedence. Either way, start a new segment.
            // A drained lane a sibling batch still references has no
            // segment to fold into; the op starts the lane's next one.
            const folded =
                lastSegment === undefined || existing.inFlight || existing.demoted?.has(lastSegment)
                    ? null
                    : foldOps(lastSegment, ops)
            if (folded === null) {
                existing.segments.push(ops)
            } else {
                existing.segments[last] = folded
            }
        }
        // The memo now holds the pending projection: every distinct id
        // resolving to this person sees the change pre-flush, and the
        // next event composes on top.
        this.memo.setProjection(personKey, projected)
        this.memo.recordResolution(batchId, `${person.team_id}:${distinctId}`, personKey)
        return [this.memo.snapshot(projected), []]
    }

    /**
     * Runs the identity service's merge saga — which owns merge
     * execution end to end: fencing, folding, repointing, tombstoning —
     * and folds its outcome into this batch's view: distinct ids the
     * saga touched resolve to the survivor, so later events in the batch
     * read the merged world, and the rest of the team's resolutions are
     * dropped so they re-resolve against it.
     */
    async mergePersons(request: MergePersonsRequest, batchId: number): Promise<MergePersonsResult> {
        // The memo's view of the named ids, captured before the fresh
        // resolve moves any edges: a fence has to cover what this pod
        // BELIEVES as well as what identity says, or a lane keyed on a
        // stale belief goes unguarded.
        const memoOf = (distinctId: string) => this.memo.resolutionOf(`${request.teamId}:${distinctId}`)
        const memoSourceKeys = request.sources.map((source) => memoOf(source.distinctId))
        const memoTargetKey = memoOf(request.targetDistinctId)
        // Resolve every named id in one batched call, the way the saga
        // will: a source person this pod has never touched still needs its
        // fence, or a first-touch fold landing mid-merge races the request
        // and gets wrongly demoted at reconcile.
        const fresh = await this.resolveForFence(
            request.teamId,
            [request.targetDistinctId, ...request.sources.map((source) => source.distinctId)],
            batchId
        )
        // Source order is precedence order, and the target cannot be
        // demoted, so only the sources carry a rank. A source may name two
        // persons — the memo's belief and identity's answer — and both are
        // fenced and, on failure, marked.
        const sourceKeys = request.sources
            .map((source, rank) => ({
                rank,
                personKeys: [
                    ...new Set(
                        [fresh.get(source.distinctId), memoSourceKeys[rank]].filter(
                            (personKey): personKey is string => personKey != null
                        )
                    ),
                ],
            }))
            .filter((entry) => entry.personKeys.length > 0)
        const targetKey = fresh.get(request.targetDistinctId) ?? memoTargetKey
        const personKeys = [
            ...new Set([
                ...(targetKey != null ? [targetKey] : []),
                ...(memoTargetKey != null ? [memoTargetKey] : []),
                ...sourceKeys.flatMap((entry) => entry.personKeys),
            ]),
        ]
        // Held for the whole call, including reconciliation, so a fold that
        // was waiting resumes against the merged world rather than into a
        // request that has already gone.
        let releaseFence: (() => void) | undefined
        let carried: CarriedLane[] = []
        try {
            releaseFence = this.fencePersons(personKeys)
            // A write launched before the fence went up is already on the
            // wire; if it lands after the saga applies the merge event's
            // $set, the older value silently overwrites the newer and the
            // scrub finds nothing left to retract. Writes re-check the fence
            // at execution start, so anything without a settle promise here
            // has not launched and will defer; this wait covers the ones
            // that did launch — bounded by their remaining segment RPCs.
            const inFlightWrites = [
                ...personKeys.map((personKey) => this.entries.get(personKey)?.directWriteSettled),
                ...personKeys.flatMap((personKey) => [...(this.redirectsInFlight.get(personKey) ?? [])]),
            ].filter((settled): settled is Promise<void> => settled !== undefined)
            if (inFlightWrites.length > 0) {
                await Promise.all(inFlightWrites)
            }
            // Collected behind the fence, so nothing can arrive between the
            // collection and the send.
            carried = this.collectCarriedOperations(personKeys)
            let result
            try {
                result = await this.runMerge(
                    request,
                    batchId,
                    carried,
                    new Map(
                        request.sources.flatMap((source, index) =>
                            memoSourceKeys[index] != null
                                ? [[source.distinctId, memoSourceKeys[index]] as [string, string]]
                                : []
                        )
                    )
                )
            } catch (error) {
                if (error instanceof PersonMergeCallFailedError) {
                    // The saga is resumable, so a call that failed may still
                    // have destroyed these sources. Marking optimistically is
                    // safe in both directions: the demote only takes effect
                    // on the redirect path, which runs only when the person
                    // really did vanish. A post-verdict throw is not this
                    // shape — its verdict arrived and reconcile handled the
                    // marking — so it propagates as itself.
                    for (const { rank, personKeys: markKeys } of sourceKeys) {
                        for (const personKey of markKeys) {
                            const entry = this.entries.get(personKey)
                            if (entry) {
                                entry.demoted = new Set(entry.segments)
                                // Never weaken a claim an earlier merge already made.
                                entry.demoteRank = Math.min(entry.demoteRank ?? rank, rank)
                            }
                        }
                    }
                }
                throw error
            }
            this.discardCarriedOperations(carried, result.carriedApplied)
            // Whatever of the target's lane could not travel — multi-segment
            // lanes, the cap, an uncarriable id — now holds ops older than
            // the merge event's own $set, which the saga has already applied
            // to the survivor. Writing them later must not overwrite it, so
            // the event's $set keys are scrubbed from the lane: the same
            // newer-write-supersedes rule foldOps applies between ordinary
            // events. The event's $set_once needs no scrub — it fills only
            // absent keys, so an older buffered value landing later yields
            // the same result either way — but one behind a buffered $unset
            // is reasserted as a trailing segment, so the leader sees the
            // two in event order.
            // Only a returned survivor proves the event's writes landed
            // somewhere; without one, scrubbing would delete buffered values
            // nothing superseded.
            const survivorLane = result.survivor ? `${request.teamId}:${result.survivor.id}` : undefined
            if (survivorLane != null) {
                this.scrubSupersededKeys(survivorLane, request.eventOps.set)
                this.reassertSetOnceBehindUnsets(survivorLane, request.eventOps)
                if (result.survivor) {
                    // The rebase inside runMerge replayed the lane before the
                    // scrub retracted keys from it; rebuilt here so the
                    // read-your-write view never shows a value the store has
                    // decided will not write.
                    this.rebaseProjection(survivorLane, result.survivor)
                }
            }
            return { ...result, survivor: this.memo.snapshot(result.survivor) }
        } finally {
            for (const { entry } of carried) {
                this.releaseWritten(`${entry.teamId}:${entry.personId}`, entry)
            }
            releaseFence?.()
        }
    }

    /**
     * Restores event order for the one composition the scrub cannot
     * express: the merge event's $set_once on a key some buffered segment
     * unsets. Sequentially the unset lands first and the $set_once fills
     * the hole, but the saga applied the $set_once at merge time, where a
     * present key makes it a no-op — and the buffered unset would then
     * delete the survivor's value with nothing refilling it. Appending the
     * colliding $set_once keys as the lane's final segment makes the
     * leader see unset-then-fill in order; against the saga's own earlier
     * attempt it is idempotent.
     */
    private reassertSetOnceBehindUnsets(personKey: string, eventOps: EventOps): void {
        const entry = this.entries.get(personKey)
        if (!entry) {
            return
        }
        const colliding = Object.fromEntries(
            Object.entries(eventOps.setOnce).filter(([key]) =>
                entry.segments.some((segment) => segment.unset.includes(key))
            )
        )
        if (Object.keys(colliding).length === 0) {
            return
        }
        entry.segments.push({
            set: {},
            setOnce: colliding,
            unset: [],
            denied: false,
            shouldForceUpdate: true,
            eventName: eventOps.eventName,
        })
        entry.triggersUpdate = true
    }

    /**
     * One batched identity resolve of a merge's named ids, answering
     * `distinctId -> personKey` for everything that resolved. Results are
     * recorded at checking grade — resolution edges are identity-backed on
     * every path — so reconcile's memo fallback sees them too. Best-effort:
     * a failed resolve degrades to the memo-only fence rather than
     * blocking the merge, and is counted so the degradation is visible.
     */
    private async resolveForFence(
        teamId: number,
        distinctIds: string[],
        batchId: number
    ): Promise<Map<string, string>> {
        const resolvedKeys = new Map<string, string>()
        try {
            const resolved = await this.repository.resolvePersonsByDistinctIds(
                distinctIds.map((distinctId) => ({ teamId, distinctId })),
                CALLER_TAG
            )
            for (const entry of resolved) {
                if (entry.person) {
                    resolvedKeys.set(entry.distinctId, `${teamId}:${entry.person.id}`)
                    this.memo.record(entry.teamId, entry.distinctId, entry.person, batchId, { grade: 'checking' })
                }
            }
        } catch (error) {
            personhogStoreMergeCacheCounter.inc({ action: 'fence_resolve_failed' })
            logger.warn('merge fence resolve failed; fencing from the memo alone', { team_id: teamId, error })
        }
        return resolvedKeys
    }

    /** Drops a newer event's $set keys from every buffered segment of a lane. */
    private scrubSupersededKeys(personKey: string, eventSet: Properties): void {
        const entry = this.entries.get(personKey)
        const keys = Object.keys(eventSet)
        if (!entry || keys.length === 0) {
            return
        }
        for (const segment of entry.segments) {
            for (const key of keys) {
                delete segment.set[key]
                delete segment.setOnce[key]
            }
            if (segment.unset.length > 0) {
                segment.unset = segment.unset.filter((key) => !(key in eventSet))
            }
        }
    }

    /**
     * The pending operations of the fenced persons, to travel inside the
     * merge request and take part in it. Marked in flight for the call's
     * duration so a concurrent flush cannot write the same segments, which
     * would leave the two truncations racing over one entry.
     *
     * Lanes stay behind — counted by reason — when one carried entry
     * cannot express them (multiple segments), when the flush would
     * suppress them anyway (no update-worthy change), when their distinct
     * id would fail the whole request (illegal, over-length, NUL,
     * duplicate), or past the service's cap. A destroyed source's leftover
     * lane redirects demoted; the survivor's own leftover lane has its
     * superseded keys scrubbed after the merge instead, since demotion is
     * source precedence and the survivor is not a source.
     *
     * No await in this method: the fence excludes folds, not the flush that
     * reads these same entries.
     */
    private collectCarriedOperations(personKeys: string[]): CarriedLane[] {
        const collected: CarriedLane[] = []
        const seen = new Set<string>()
        const visited = new Set<string>()
        for (const personKey of personKeys) {
            // The target and a source can resolve to one person; a second
            // visit is not a skipped lane.
            if (visited.has(personKey)) {
                continue
            }
            visited.add(personKey)
            const entry = this.entries.get(personKey)
            if (!entry || !entry.triggersUpdate) {
                continue
            }
            if (entry.inFlight || entry.segments.length !== 1) {
                personhogStoreCarriedSkippedCounter.inc({
                    reason: entry.inFlight ? 'in_flight' : 'multi_segment',
                })
                continue
            }
            // The service answers an illegal, over-length, or NUL-bearing
            // carried id with INVALID_ARGUMENT for the whole request, which
            // would fail a merge that has nothing wrong with it. A lane's
            // distinct id is whichever one folded first for that person, so
            // it is not already held to the merge's own id rules. Length is
            // counted in code points, matching the server's chars().count().
            if (
                isDistinctIdIllegal(entry.distinctId) ||
                [...entry.distinctId].length > MAX_CARRIED_DISTINCT_ID_LENGTH ||
                entry.distinctId.includes('\u0000')
            ) {
                personhogStoreCarriedSkippedCounter.inc({ reason: 'illegal_id' })
                continue
            }
            // The service rejects a request naming one distinct id twice,
            // which two persons folded under the same id would produce.
            if (seen.has(entry.distinctId)) {
                personhogStoreCarriedSkippedCounter.inc({ reason: 'duplicate_id' })
                continue
            }
            seen.add(entry.distinctId)
            if (collected.length === MAX_CARRIED_LANES) {
                // Counted per qualifying lane turned away, so the metric
                // reads as lanes affected rather than merges affected.
                personhogStoreCarriedSkippedCounter.inc({ reason: 'cap' })
                continue
            }
            entry.inFlight = true
            collected.push({ entry, ops: entry.segments[0] })
        }
        return collected
    }

    /**
     * Drop the operations the service says it applied. Anything it did not
     * name stays, whether because it predates the field, because the call
     * was a replay, or because its write failed.
     */
    private discardCarriedOperations(carried: CarriedLane[], applied: string[]): void {
        const appliedIds = new Set(applied)
        let discarded = 0
        for (const { entry, ops } of carried) {
            if (appliedIds.has(entry.distinctId) && entry.segments[0] === ops) {
                entry.segments.shift()
                // The mark is keyed by segment identity, so dropping the
                // segment drops its claim with it.
                entry.demoted?.delete(ops)
                discarded++
                if (entry.segments.length === 0) {
                    entry.triggersUpdate = false
                    entry.demoted = undefined
                }
            }
        }
        // Counted from what this dropped rather than from what the response
        // named, so the two always sum to what was sent.
        personhogStoreCarriedCounter.inc({ outcome: 'applied' }, discarded)
        personhogStoreCarriedCounter.inc({ outcome: 'retained' }, carried.length - discarded)
    }

    private async runMerge(
        request: MergePersonsRequest,
        batchId: number,
        carried: CarriedLane[],
        beliefs: Map<string, string>
    ): Promise<MergePersonsResult & { carriedApplied: string[] }> {
        // The saga records verdicts durably against the op id, and two of
        // its answers must be escaped with a fresh op identity rather than
        // replayed. A recorded skipped_conflict is transient — the holding
        // operation finishes — so each retry salts a counter suffix into
        // the derivation for a genuinely fresh look, and exhaustion throws
        // the claim error the Postgres merge throws, converging the two
        // backends on one thrown-conflict vocabulary. A FAILED_PRECONDITION
        // means the recorded op froze a different payload than this
        // delivery computed (payloads drift across deliveries: GeoIP
        // refreshes, transformation stamps), so its salt is the payload
        // fingerprint — stable within a delivery, so retries attach to what
        // the salted op recorded, fresh for a drifted one; a counter would
        // restart every delivery and wedge once a few drifted redeliveries
        // exhaust its reachable ids. Both escapes are single-source only,
        // matching the sequential path folds fall back to. Neither can
        // double-merge: a conflict verdict proves the aborted op destroyed
        // nothing, and a fresh op against an already-merged graph settles
        // as noop_same_person. Fences stay held across attempts, so the
        // lanes stay quiesced throughout.
        const singleSource = request.sources.length === 1
        let payloadSalted = false
        let conflictRetries = 0
        let result
        while (true) {
            const eventKey = payloadSalted
                ? `${request.opId}#fp${mergePayloadFingerprint(
                      request.eventOps.set,
                      request.eventOps.setOnce,
                      request.createdAtMs
                  )}`
                : request.opId
            try {
                result = await this.repository.mergePersons(
                    {
                        teamId: request.teamId,
                        targetDistinctId: request.targetDistinctId,
                        sources: request.sources,
                        eventSet: request.eventOps.set,
                        eventSetOnce: request.eventOps.setOnce,
                        // Event uuids are client-supplied and the saga's op keyspace
                        // is global, so a raw uuid from one team could collide with
                        // another team's recorded op and fail its merge. The uuidv5
                        // derivation scopes the op per team, and carrying the source
                        // list keeps a fold and the single-source merges it falls
                        // back to on separate keys, which the saga requires.
                        opId: mergeOpIdFromRequest(
                            request.teamId,
                            conflictRetries === 0 ? eventKey : `${eventKey}#conflict${conflictRetries}`,
                            request.sources.map((source) => source.distinctId),
                            moveLimitFor(request.mergeMode, this.options.syncMergeMoveLimit)
                        ),
                        allowIdentifiedSources: request.allowIdentifiedSources,
                        // The ASYNC and LIMIT limits come from a different knob than
                        // the constructor validates and reach BigInt() here, so they
                        // are held to the same contract.
                        moveLimit: moveLimitFor(request.mergeMode, this.options.syncMergeMoveLimit),
                        createdAtMs: request.createdAtMs,
                        // Every field the segment holds travels, because the
                        // echo makes this call discard the segment outright:
                        // anything left behind here is lost, not deferred.
                        carriedOperations: carried.map(({ entry, ops }) => ({
                            distinctId: entry.distinctId,
                            set: ops.set,
                            setOnce: ops.setOnce,
                            unset: ops.unset,
                            eventName: ops.eventName,
                            isIdentified: ops.isIdentified,
                            lastSeenAtMs: ops.lastSeenAtMs,
                            // Pins the write to the person these ops were folded
                            // for; a repoint by another pod then skips it, and
                            // the unechoed lane writes through the flush instead.
                            expectedPersonId: entry.personId,
                        })),
                    },
                    CALLER_TAG
                )
            } catch (error) {
                // INVALID_ARGUMENT is a verdict, not an unknowable failure: the
                // request was refused before any durable work, and redelivery
                // presents the same request to the same validation forever.
                // Wrapping it would turn one malformed id into a permanently
                // wedged partition, so it propagates raw to the merge service's
                // generic catch, which acks it loudly — the same terminal
                // classification the Postgres backend gives this class.
                if (error instanceof ConnectError && error.code === Code.InvalidArgument) {
                    personhogStoreMergeCallFailedCounter.inc({ error: 'InvalidArgumentSettled' })
                    throw error
                }
                if (error instanceof ConnectError && error.code === Code.FailedPrecondition) {
                    // The replay guard refusing this request shape — no
                    // durable work happened on this call, so the team view
                    // needs no invalidation. First refusal: salt and go
                    // again. A refusal of the salted id too means this exact
                    // payload is recorded with something else entirely, an
                    // unknowable state the wrapper below hands to the
                    // service to fail the batch on.
                    if (singleSource && !payloadSalted) {
                        payloadSalted = true
                        continue
                    }
                } else {
                    // The saga records its progress step by step and stays
                    // resumable, so a failed call may still have sealed sources
                    // or flipped their distinct ids onto the survivor. How far
                    // it got is unknowable from here, so the batch view is
                    // invalidated as though it had.
                    this.invalidateTeamAfterFailedMerge(request.teamId)
                }
                // No verdict arrived, so an ack would lose the merge whenever the
                // saga did not commit. The typed wrapper makes the backend-agnostic
                // merge service fail the batch — redelivery replays the saga
                // idempotently — while the Postgres path, which never produces
                // this type, keeps its current handling. Only the call wears the
                // wrapper: a bug in post-verdict processing surfaces as itself.
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
        // Request order is property precedence: an earlier source beats a
        // later one. The server answers in request order, so the index is
        // the rank a demoted redirect has to land in.
        const merged = result.results.filter((source) => source.outcome === 'merged')
        this.reconcileMergedPersons(
            request.teamId,
            merged.map((source, rank) => ({
                rank,
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
        if (result.survivor) {
            // The survivor carries what the merge folded in, which no local
            // projection knows about, so it replaces the baseline rather than
            // losing to it. The lane's own unwritten ops go back on top, or
            // the batch would stop seeing its own earlier writes.
            this.rebaseProjection(`${request.teamId}:${result.survivor.id}`, result.survivor)
            // The survivor is the folded document the leader produced —
            // authoritative, so these ids serve the update read class.
            this.memo.record(request.teamId, request.targetDistinctId, result.survivor, batchId, { grade: 'update' })
            for (const distinctId of touched) {
                this.memo.record(request.teamId, distinctId, result.survivor, batchId, { grade: 'update' })
            }
        }
        return { survivor: result.survivor, results: result.results, carriedApplied: result.carriedApplied }
    }

    /** The leader enforces the size ceiling at admission; there is nothing to measure here. */
    personPropertiesSize(_personId: string, _teamId: number): Promise<number> {
        return Promise.resolve(0)
    }

    getFlushStats(): BatchWritingStoreFlushStats {
        return {
            dirtyEntryCount: [...this.entries.values()].filter((entry) => entry.segments.length > 0).length,
            referencedBatchCount: this.batchEntryKeys.size,
            cacheEntryCount: this.memo.projectionCount,
        }
    }

    /**
     * A direct diff update, applied immediately rather than folded: the
     * caller has already resolved the diff, so it maps one-to-one onto
     * the leader's folded-update RPC. Only the diff-expressible fields of
     * `otherUpdates` are supported; anything else has no RPC field, and
     * silently dropping it would diverge, so it fails loudly instead.
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
        const unsupported = Object.keys(otherUpdates).filter((key) => key !== 'is_identified' && key !== 'last_seen_at')
        if (unsupported.length > 0) {
            throw new PersonhogPendingRpcError(
                'updatePersonWithPropertiesDiffForUpdate',
                `UpdatePersonProperties fields for ${unsupported.join(', ')}`
            )
        }
        const { person: updated } = await this.repository.updatePersonProperties(
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
        if (!updated) {
            return [person, [], false]
        }
        // No ClickHouse message: the leader's changelog is this backend's
        // person feed, so emitting here would double-publish.
        return [updated, [], false]
    }

    /**
     * One identity batch resolve for the batch's distinct ids, then
     * leader state reads for the hits — the same two-step the update
     * fetch does singly, done once up front so per-event processing hits
     * the memo. Best-effort: a failed prefetch leaves resolution to
     * first touch.
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
        // Captured before the resolve goes out: a merge rewriting the memo
        // while this response is in flight makes every fill suspect — the
        // absence it would fill may be a resolution the merge released.
        const issuedAt = this.memo.generation
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
                        if (this.memo.generation !== issuedAt) {
                            return
                        }
                        if (!entry.person) {
                            this.memo.record(entry.teamId, entry.distinctId, null, batchId, { grade: 'update' })
                            return
                        }
                        const person = await this.repository.fetchPersonById(entry.teamId, entry.person.id, CALLER_TAG)
                        if (this.memo.generation !== issuedAt) {
                            return
                        }
                        // Fill-only: this response raced everything the batch
                        // did since the request went out.
                        this.memo.record(entry.teamId, entry.distinctId, person, batchId, {
                            grade: 'update',
                            fillOnly: true,
                        })
                    })
                )
            )
        } catch (error) {
            logger.warn('personhog prefetch failed; resolution falls back to first touch', { error })
        }
    }

    /**
     * Writes every batch's folded lanes to the leader, one entry per
     * person, segments in order. There is deliberately no Postgres
     * fallback, and nothing publishes: the leader's changelog is this
     * backend's person feed. A missing person redirects to whatever its
     * distinct id resolves to now; a person genuinely gone, and the
     * leader's size rejection, are counted and dropped, since neither can
     * succeed on retry. Identity lag that outlasts the redirect's refresh
     * budget, and any other failure, fail the flush so the batch retries
     * whole.
     *
     * Passes serialize, one at a time, with later calls queueing behind
     * the running one. A pass snapshots how many segments each lane holds
     * before writing and removes each segment as it lands, so a failure
     * part way through keeps everything it did not attempt. The failing
     * call fails its own batch, but the entry may belong to a sibling batch
     * that never acked its events, and folds are idempotent, so a later
     * pass writes what remains again.
     *
     * A lane entry with no update-worthy change — every refined change
     * filtered, nothing forced, no scalar movement — is suppressed here
     * rather than written, the same no-op classification the Postgres store
     * applies at its flush. `triggersUpdate` accumulates across every batch
     * folding into the entry, so one batch's real change carries a sibling's
     * filtered-only fold along with it.
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
        // A flush returning success is what lets its batch ack, so it must
        // not return while any lane still holds unwritten segments — a lane
        // parked behind an in-flight merge (fenced, or carried in flight)
        // has to be waited out and written, or the pass has to fail so the
        // batch redelivers. Acking past a parked lane would commit offsets
        // over writes that only exist in this process.
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
            // Wait out whatever is still fenced; a fence already released
            // needs no wait — the next round simply re-captures its lane.
            for (const [personKey, entry] of this.entries) {
                if (entry.segments.length === 0) {
                    continue
                }
                const fence = this.fences.get(personKey)
                if (fence) {
                    await this.awaitFences(personKey, fence)
                }
            }
        }
    }

    private async writeEligibleLanes(countDeferrals: boolean, pass: { deferrals: number }): Promise<void> {
        // Entries are never removed in order to be written. A pass records
        // how many segments each one holds right now, marks it in flight,
        // and truncates exactly that many on success. A failure therefore
        // leaves the entry exactly as it was — there is no claim to strand
        // and no restore path to get wrong — and ops folded while the write
        // is in flight land in a fresh segment behind the snapshot.
        // No await in this block: the snapshot has to be atomic.
        const captured: { personKey: string; entry: OpsLaneEntry; segments: number }[] = []
        for (const [personKey, entry] of this.entries) {
            if (entry.segments.length === 0) {
                continue
            }
            if (entry.inFlight) {
                // Capture is synchronous and passes serialize, so in-flight
                // here means a merge carried this lane. Its merge may fail
                // and retain the segments, so the round is not done with it:
                // an uncounted skip would let the flush resolve — and the
                // batch ack — over segments a failed merge hands back.
                pass.deferrals += 1
                continue
            }
            // A fenced person's merge is on the wire. Writing its lane now
            // could hit the tombstone and redirect raw before reconcile marks
            // the lane for demotion — the wrong-precedence landing the
            // demote machinery exists to prevent. The drain loop above waits
            // the merge out and writes it before the flush returns.
            if (this.fences.has(personKey)) {
                pass.deferrals += 1
                if (countDeferrals) {
                    personhogStoreFlushCounter.inc({ outcome: 'deferred_fenced' })
                }
                continue
            }
            entry.inFlight = true
            captured.push({ personKey, entry, segments: entry.segments.length })
        }
        // A demoted lane contributes $set_once, which resolves first-wins,
        // so lanes demoted by one merge have to reach the survivor in that
        // merge's source order. They write in rank order, one at a time,
        // while everything else fans out.
        const ordered = captured
            .filter(({ entry }) => this.leadsWithDemoted(entry))
            .sort((a, b) => (a.entry.demoteRank ?? 0) - (b.entry.demoteRank ?? 0))
        const concurrent = captured.filter(({ entry }) => !this.leadsWithDemoted(entry))

        const limit = pLimit(this.options.maxConcurrentUpdates)
        const outcomes = await Promise.allSettled([
            ...concurrent.map(({ personKey, entry, segments }) =>
                limit(() => this.writeEntry(personKey, entry, segments, pass))
            ),
            limit(async () => {
                let failure: unknown
                for (const { personKey, entry, segments } of ordered) {
                    if (failure !== undefined) {
                        // Writing past a failed lane would land out of the
                        // merge's source order. The mark still has to go, or
                        // every later pass skips this entry and its writes
                        // are stranded for the process lifetime.
                        this.releaseWritten(personKey, entry)
                        continue
                    }
                    try {
                        await this.writeEntry(personKey, entry, segments, pass)
                    } catch (error) {
                        failure = error
                    }
                }
                if (failure !== undefined) {
                    throw failure
                }
            }),
        ])
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
        if (entry.segments.length > 0) {
            return
        }
        entry.triggersUpdate = false
        entry.demoted = undefined
        entry.demoteRank = undefined
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
        pass?: { deferrals: number }
    ): Promise<void> {
        // Capture marked this lane, but execution may begin macrotasks later
        // (a pLimit slot, the ordered chain). A merge can fence the person in
        // that gap, and its in-flight-write wait cannot see a write that has
        // not created its promise yet — so the fence is re-checked HERE, at
        // the moment writing actually starts. A fenced lane defers to the
        // drain loop, which writes it after the merge with the scrubs and
        // demote marks in place.
        if (this.fences.has(personKey)) {
            personhogStoreFlushCounter.inc({ outcome: 'deferred_fenced_at_start' })
            if (pass) {
                pass.deferrals += 1
            }
            this.releaseWritten(personKey, entry)
            return
        }
        let settleDirectWrite: () => void = () => {}
        entry.directWriteSettled = new Promise((resolve) => {
            settleDirectWrite = resolve
        })
        try {
            if (!entry.triggersUpdate) {
                personhogStoreFlushCounter.inc({ outcome: 'filtered' })
                this.dropLeadingSegments(entry, segments)
                return
            }
            // Counts segments this pass actually removed by writing them,
            // across the direct attempts and any redirect. The discard bound is
            // snapshot minus written minus dropped — array length is no
            // substitute, since folds arriving during a redirect's waits
            // inflate it with segments this pass never attempted and must
            // not discard.
            const progress = { written: 0 }
            let dropped = 0
            // A size rejection removes only the rejected unit; the rest of
            // the snapshot is still writable RIGHT NOW, and the flush must
            // not resolve — and the batch must not ack — over it. Looping
            // here honors that without burning a drain round on a lane
            // nothing is fencing. Terminates: every iteration writes the
            // whole remainder, drops at least one unit, transitions to the
            // redirect phase once, or exits by throw.
            let viaRedirect = false
            while (segments - progress.written - dropped > 0) {
                const budget = segments - progress.written - dropped
                try {
                    if (viaRedirect) {
                        // The effective snapshot shrinks by what was dropped;
                        // the redirect derives its own remaining budget from it.
                        let outcome: RedirectOutcome
                        try {
                            outcome = await this.redirectToSurvivor(entry, segments - dropped, progress)
                        } catch (redirectError) {
                            if (!(redirectError instanceof CountedRedirectError)) {
                                personhogStoreFlushCounter.inc({ outcome: 'error' })
                            }
                            throw redirectError
                        }
                        personhogStoreFlushCounter.inc({
                            outcome: { written: 'redirected', gone: 'not_found', size_violation: 'size_violation' }[
                                outcome
                            ],
                        })
                        if (outcome === 'gone') {
                            this.dropLeadingSegments(entry, Math.max(0, segments - progress.written - dropped))
                            break
                        }
                        if (outcome === 'size_violation') {
                            // Only the rejected unit can never succeed; the
                            // remainder re-enters the redirect with the person
                            // still gone.
                            this.dropLeadingSegments(entry, 1)
                            dropped += 1
                            continue
                        }
                        break
                    }
                    await this.writeSegments(entry, entry.personId, budget, false, progress)
                    personhogStoreFlushCounter.inc({ outcome: 'success' })
                    break
                } catch (error) {
                    if (error instanceof NoRowsUpdatedError) {
                        // The person was merged or deleted since the fold.
                        // Settled before the redirect phase: the redirect waits
                        // on merge fences, and a merge waiting on this
                        // promise would be a cycle. A size-drop resume, by
                        // contrast, keeps the promise pending — the resumed
                        // write is still a direct write the merge must order
                        // behind.
                        settleDirectWrite()
                        viaRedirect = true
                        continue
                    }
                    if (error instanceof PersonhogPropertiesSizeError) {
                        // The rejected segment can never succeed, so it goes
                        // and the loop writes the remainder now. Counted only:
                        // the store holds no outputs handle, so the
                        // size-violation ingestion warning the Postgres store
                        // emits has no path from here.
                        personhogStoreFlushCounter.inc({ outcome: 'size_violation' })
                        this.dropLeadingSegments(entry, 1)
                        dropped += 1
                        continue
                    }
                    personhogStoreFlushCounter.inc({ outcome: 'error' })
                    logger.error('Failed to flush folded update to personhog', {
                        teamId: entry.teamId,
                        personId: entry.personId,
                        error,
                    })
                    // The unwritten segments stay in the entry, so the next
                    // pass writes them again rather than losing writes the
                    // batch holds.
                    throw error
                }
            }
        } finally {
            settleDirectWrite()
            entry.directWriteSettled = undefined
            this.releaseWritten(personKey, entry)
        }
    }

    /**
     * The one operation a lane contributes to a survivor it reaches after
     * its own person was merged away.
     *
     * A merge resolves a key both persons hold in the target's favour and
     * contributes the source's value only where the target has none, which
     * is what $set_once expresses. So the lane's whole net effect travels
     * as $set_once and its $unset keys travel as nothing: the target's
     * value survives a merge regardless.
     *
     * The net has to be computed across the whole lane rather than segment
     * by segment, because $set_once resolves in arrival order. Demoting
     * each segment on its own would let an early value win over the later
     * one that actually stood, and would re-contribute a key a later
     * segment deleted.
     *
     * Over-contributing is safe in the other direction: a key the source
     * already held reached the survivor through the merge itself, so a
     * $set_once for it is a no-op. Only keys neither person had are filled.
     */
    private demoteSegments(segments: EventOps[]): EventOps {
        const contributed = new Map<string, unknown>()
        let isIdentified: true | undefined
        let lastSeenAtMs: number | undefined
        for (const ops of segments) {
            // $set_once fills only what the lane has not already decided;
            // $set always wins; $unset withdraws — except a pair (set and
            // unset of one key in one event), which the leader resolves to
            // gone where the key was present before the op and to the set
            // value where it was absent. Presence here is what the lane had
            // contributed before this segment.
            const presentBefore = new Set(contributed.keys())
            for (const [key, value] of Object.entries(ops.setOnce)) {
                if (!contributed.has(key)) {
                    contributed.set(key, value)
                }
            }
            for (const [key, value] of Object.entries(ops.set)) {
                contributed.set(key, value)
            }
            for (const key of ops.unset) {
                if (!(key in ops.set || key in ops.setOnce) || presentBefore.has(key)) {
                    contributed.delete(key)
                }
            }
            // Identity and last-seen are not property precedence: they
            // advance regardless of who won the merge.
            isIdentified = ops.isIdentified || isIdentified ? true : undefined
            lastSeenAtMs = Math.max(lastSeenAtMs ?? 0, ops.lastSeenAtMs ?? 0) || undefined
        }
        // The base segment names the write. A denied event can end the run
        // (it contributes scalars), but writing the net under its name
        // would make the leader's denylist discard every property the run
        // contributed — so the name comes from the last property-bearing
        // segment.
        const last = [...segments].reverse().find((segment) => !segment.denied) ?? segments[segments.length - 1]
        return {
            ...last,
            set: {},
            setOnce: Object.fromEntries(contributed) as Properties,
            unset: [],
            isIdentified,
            lastSeenAtMs,
        }
    }

    /**
     * Reinstates a merged person's projection on top of the merge's own
     * result. The memo's record deliberately refuses to overwrite a projection
     * that has ops folded behind it, because an ordinary re-fetch answers
     * committed state that predates them; a merge survivor is the one
     * answer that is not stale, so it is installed here and the lane's
     * pending ops are replayed over it.
     */
    private rebaseProjection(personKey: string, survivor: InternalPerson): void {
        const entry = this.entries.get(personKey)
        if (!entry || entry.segments.length === 0) {
            this.memo.setProjection(personKey, survivor)
            return
        }
        const properties = { ...survivor.properties }
        for (const ops of entry.segments) {
            // The leader's $unset removes only keys present BEFORE the op,
            // so a pair — one event both setting and unsetting a key —
            // resolves to gone where the key was present and to the set
            // value where it was absent. Presence is captured before this
            // segment's writes apply.
            const presentBefore = new Set(Object.keys(properties))
            for (const [key, value] of Object.entries(ops.setOnce)) {
                if (!(key in properties)) {
                    properties[key] = value
                }
            }
            Object.assign(properties, ops.set)
            for (const key of ops.unset) {
                // A pair — the same op both writing (set OR set_once) and
                // unsetting a key — resolves to gone only where the key was
                // present before the op; the leader's unset checks the
                // pre-op document.
                if (!(key in ops.set || key in ops.setOnce) || presentBefore.has(key)) {
                    delete properties[key]
                }
            }
        }
        this.memo.setProjection(personKey, { ...survivor, properties })
    }

    /** Whether the leading segment predates a merge that destroyed this person. */
    private leadsWithDemoted(entry: OpsLaneEntry): boolean {
        return entry.segments.length > 0 && entry.demoted?.has(entry.segments[0]) === true
    }

    private async writeOne(entry: OpsLaneEntry, personId: string, ops: EventOps): Promise<void> {
        await this.repository.updatePersonProperties(
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
    }

    /**
     * Writes a lane's leading segments, removing each as it lands so a
     * failure part way through never discards what has not been attempted.
     * Demoted lanes write as one operation, since the demote is defined over
     * the lane's net effect rather than per segment.
     */
    /**
     * Removes the lane's leading segments after they written (or were
     * judged unwritable), keeping the demote mark set in step so it never
     * pins removed objects or misclassifies survivors.
     */
    private dropLeadingSegments(entry: OpsLaneEntry, count: number): void {
        for (const dropped of entry.segments.splice(0, count)) {
            entry.demoted?.delete(dropped)
        }
    }

    private async writeSegments(
        entry: OpsLaneEntry,
        personId: string,
        segments: number,
        demote = false,
        progress?: { written: number }
    ): Promise<void> {
        const count = Math.min(segments, entry.segments.length)
        if (count === 0) {
            return
        }
        // Only the leading run that predates the merge travels demoted, and
        // it travels as one operation: the demote is defined over a lane's
        // net effect, so splitting the marked run across passes would let
        // an early value win first-wins over the one that stood. The run
        // therefore writes whole even past the snapshot count — this lane is
        // in flight, so no other writer can touch it, and a marked segment
        // predates the merge in every case but a fold that outwaited the
        // fence's timeout, whose ordering was forfeited with the timeout.
        // Anything unmarked writes as itself, bounded by the snapshot.
        let prefix = 0
        if (demote) {
            while (prefix < entry.segments.length && entry.demoted?.has(entry.segments[prefix])) {
                prefix++
            }
        }
        if (prefix > 0) {
            await this.writeOne(entry, personId, this.demoteSegments(entry.segments.slice(0, prefix)))
            this.dropLeadingSegments(entry, prefix)
            if (progress) {
                progress.written += prefix
            }
        }
        for (let written = prefix; written < count; written++) {
            await this.writeOne(entry, personId, entry.segments[0])
            this.dropLeadingSegments(entry, 1)
            if (progress) {
                progress.written += 1
            }
        }
    }

    /**
     * Re-resolves a lane's distinct id after its person vanished and writes
     * the snapshot to the survivor. Answers 'gone' when nothing resolves,
     * when the id still maps to the vanished person, or when the survivor
     * is also gone by write time. A transient failure rethrows with the
     * segments still in the entry, so the flush retries them whole.
     */
    private async redirectToSurvivor(
        entry: OpsLaneEntry,
        segments: number,
        progress: { written: number }
    ): Promise<RedirectOutcome> {
        // Each pass re-resolves against the person the previous one failed
        // to write, so consecutive merges on the same lineage converge
        // instead of dropping on the second one. Postgres loops its refresh
        // for the same reason.
        // A lane captured before its person was fenced can reach this path
        // mid-merge: identity's flip becomes visible before the merge RPC
        // returns and reconcile marks the lane. Writing then would land the
        // pre-merge ops raw. Waiting the fence out first means the marks —
        // and the repointed resolution — exist before anything writes.
        const fence = this.fences.get(`${entry.teamId}:${entry.personId}`)
        if (fence) {
            await this.awaitFences(`${entry.teamId}:${entry.personId}`, fence)
        }
        let vanished = entry.personId
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
                // The top-of-redirect fence wait is one check; a merge can
                // fence either person after it. Writing under a live fence
                // lands pre-merge ops after the saga's own writes, so any
                // fence found now is waited out and the attempt restarts
                // with a fresh resolve.
                const fencedKey = [
                    `${entry.teamId}:${vanished}`,
                    ...(survivorId !== undefined ? [`${entry.teamId}:${survivorId}`] : []),
                ].find((key) => this.fences.has(key))
                if (fencedKey !== undefined) {
                    await this.awaitFences(fencedKey, this.fences.get(fencedKey)!)
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
                        // Still resolving to the person the leader lost is
                        // the lag shape, not the deleted shape: the write
                        // went to the leader and this read went to identity,
                        // which lags it. Dropping here would lose real
                        // writes whenever lag outruns the refresh budget, so
                        // the batch fails and redelivers instead.
                        personhogStoreFlushCounter.inc({ outcome: 'redirect_lagged' })
                        throw new CountedRedirectError(
                            `identity still resolves ${entry.distinctId} to vanished person ` +
                                `${vanished} in team ${entry.teamId}; failing the flush rather than dropping`
                        )
                    }
                    return 'gone'
                }
                // Registered before the write goes on the wire: the fence
                // recheck above and this registration are one synchronous
                // block, and a merge's fence-install and registry check are
                // another, so either the merge sees this redirect and waits,
                // or this attempt saw the fence and waited. Without the
                // registration, a merge fencing the survivor mid-RPC could
                // land its own writes first and have these older ops
                // overwrite them.
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
                    await this.writeSegments(entry, survivorId, segments - progress.written, true, progress)
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
                return 'written'
            } catch (error) {
                if (error instanceof NoRowsUpdatedError) {
                    // The person this pass resolved is gone too; the next pass
                    // must not settle for it again.
                    vanished = survivorId ?? vanished
                    continue
                }
                if (error instanceof PersonhogPropertiesSizeError) {
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
     * Two keys, because neither alone is sufficient. The person ids the
     * merge reports reach ids the request never named, but a server that
     * predates the field — or an op row written before it existed —
     * reports none. The named source distinct ids are always present, and
     * resolving them through the memo recovers the same person keys
     * whenever the batch happened to touch those ids. Using both means a
     * missing field degrades to the older behavior instead of to nothing.
     *
     * A lane still holding ops for a destroyed person keeps them: they
     * missed the merge, so they are marked to redirect with source
     * precedence and land on the survivor without taking a key conflict
     * the target won. Postgres drops those buffered ops outright when it
     * clears the source, so applying them late keeps writes that backend
     * loses.
     */
    private reconcileMergedPersons(
        teamId: number,
        destroyed: DestroyedSource[],
        survivorKey: string | undefined,
        batchId: number
    ): void {
        // Two classes of dead person, because the evidence differs.
        // A server-named person id is authoritative: that person is
        // permanently gone, its ids belong to the survivor, its projection
        // must go. A key inferred from this store's own memo is only as
        // good as the memo — a replayed verdict or a merge performed on
        // another pod can make it name a live person — so inferred keys
        // are handled conservatively: lanes are marked (the only signal a
        // server that omits ids leaves), but resolutions are released to
        // re-resolve rather than repointed, and projections are left to
        // the refcounts.
        const authoritative = new Map<string, number>()
        const inferred = new Map<string, number>()
        const claim = (target: Map<string, number>, personKey: string, rank: number): void => {
            const held = target.get(personKey)
            if (held === undefined || rank < held) {
                target.set(personKey, rank)
            }
        }
        for (const { rank, personKey, distinctKey, beliefKey } of destroyed) {
            if (personKey !== undefined) {
                claim(authoritative, personKey, rank)
            }
            const resolved = this.memo.resolutionOf(distinctKey)
            if (resolved != null) {
                claim(inferred, resolved, rank)
            }
            // The belief predates the merge's own resolve, which has already
            // rewritten this edge; without the captured copy, a lane folded
            // under the stale belief would never be claimed and its ops
            // would redirect raw.
            if (beliefKey !== undefined) {
                claim(inferred, beliefKey, rank)
            }
        }
        for (const personKey of authoritative.keys()) {
            inferred.delete(personKey)
        }
        // The saga answers noop_same_person for same-person pairs, so the
        // survivor is never a destroyed source of its own merge; a memo
        // edge that says otherwise is stale (a replayed verdict whose
        // source id was already repointed) and claims nothing.
        if (survivorKey !== undefined) {
            authoritative.delete(survivorKey)
            inferred.delete(survivorKey)
        }
        if (authoritative.size === 0 && inferred.size === 0) {
            return
        }
        let stranded = 0
        for (const [personKey, entry] of this.entries) {
            const rank = authoritative.get(personKey) ?? inferred.get(personKey)
            if (rank !== undefined) {
                entry.demoted = new Set(entry.segments)
                entry.demoteRank = Math.min(entry.demoteRank ?? rank, rank)
                stranded++
            }
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
                    // including ones this request never named. Leaving them
                    // unresolved would send a fold that resumes after the
                    // fence back to the person the merge destroyed. The edge
                    // change clears the key's grade; re-granted here because
                    // the survivor's installed state is the folded document —
                    // authoritative for the update class.
                    this.memo.recordResolution(batchId, key, survivorKey)
                    this.memo.markUpdateGrade(key)
                } else {
                    this.memo.releaseResolution(key)
                }
                cleared++
            } else if (inferred.has(personKey)) {
                this.memo.releaseResolution(key)
                cleared++
            }
        }
        this.memo.bumpGeneration()
        personhogStoreMergeCacheCounter.inc({ action: 'resolution_cleared' }, cleared)
        for (const personKey of authoritative.keys()) {
            // The person no longer exists, so its projection goes whatever
            // still names it; the ids were just repointed or released.
            this.memo.deletePerson(personKey)
        }
        if (stranded > 0) {
            personhogStoreMergeCacheCounter.inc({ action: 'lane_stranded' }, stranded)
            logger.warn('🤔', 'merge destroyed a person still holding folded ops; they will apply after the merge', {
                team_id: teamId,
                lanes: stranded,
            })
        }
    }

    /**
     * The saga records its progress step by step and stays resumable, so a
     * failed call may still have destroyed persons this batch has cached.
     * Which ones is unknowable from here — no verdicts arrived — so the
     * team's resolutions are dropped and re-resolve on next access.
     *
     * Person documents are dropped only for persons holding no folded ops.
     * A document with a pending lane behind it is the batch's own
     * read-your-write view, and the memo's record will overwrite it with
     * service state once it is absent, so dropping it would hide this
     * batch's earlier updates from its own later events. Re-resolution
     * repoints the ids; the projection stays until its ops write.
     */
    private invalidateTeamAfterFailedMerge(teamId: number): void {
        const cleared = this.memo.invalidateTeam(teamId)
        personhogStoreMergeCacheCounter.inc({ action: 'invalidated_after_failure' }, cleared)
    }

    /**
     * Frees a completed batch's memos and drops its references to shared
     * entries, mirroring the Postgres store's post-flush release. Entries
     * are reference-counted because they are shared: one batch finishing
     * must not evict ops another batch is still folding into. An entry that
     * still holds unwritten ops when its last reference goes is deferred
     * rather than evicted, so releasing never discards a write.
     */
    releaseBatch(batchId: number): void {
        // Entries first: a projection outlives its resolutions only while a
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
    }

    /**
     * Drops a drained entry and, with it, the projection it was keeping
     * alive when no resolution still names that person.
     */
    private retireEntry(personKey: string): void {
        this.entries.delete(personKey)
        this.memo.evictProjection(personKey)
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
     * Whether any open batch still names this person's entry. A scan over
     * the open batches' key sets rather than a maintained counter: `has` is
     * constant time and batches number in the handful, while a counter that
     * can drift out of step with the sets is a whole bug class for nothing.
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
        if (this.entries.size > 0) {
            return Promise.reject(
                new Error(`PersonhogPersonsStore shut down with ${this.entries.size} lanes holding unwritten ops`)
            )
        }
        return Promise.resolve()
    }
}
