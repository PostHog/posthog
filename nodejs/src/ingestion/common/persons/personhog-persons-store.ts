import { Code, ConnectError } from '@connectrpc/connect'
import { DateTime } from 'luxon'
import pLimit from 'p-limit'
import { Counter } from 'prom-client'

import { TRANSPORT_MAX_RETRIES } from '~/common/personhog/grpc-retry'
import { SEMANTIC_REFUSAL_METADATA_KEY, SEMANTIC_REFUSAL_OP_ID_REUSED } from '~/common/personhog/identity'
import { errorClassLabel } from '~/common/personhog/metrics'
import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogFencedError, PersonhogPropertiesSizeError } from '~/common/personhog/persons'
import { PersonMessage } from '~/common/persons/person-message'
import { PersonClaimedByLifecycleOpError } from '~/common/persons/repositories/person-repository'
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
import { FlushResult, MergePersonsRequest, MergePersonsResult, PersonsStore } from './persons-store'
import { BatchBoundPersonsStore, PersonsStoreForBatch } from './persons-store-for-batch'

export const personhogStoreFlushCounter = new Counter({
    name: 'personhog_store_flush_ops_total',
    help: 'Lane write outcomes across the flush and merge-side paths, by outcome',
    labelNames: ['outcome'],
})

export const personhogStoreCachePurgeCounter = new Counter({
    name: 'personhog_store_cache_purge_total',
    help: 'Cache entries (resolution edges and person documents) discarded by a purge, by reason',
    labelNames: ['reason'],
})

export const personhogStoreMergeDrainCounter = new Counter({
    name: 'personhog_store_merge_drain_total',
    help: 'What the pre-merge drain did with each affected lane, by action',
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
    help: 'Merge calls that failed with no verdict, retried and then given up, by error class',
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
    /** The injected repository's per-request timeout; the flush's lane wait derives from it. */
    requestTimeoutMs: number
}

const DEFAULT_OPTIONS: PersonhogPersonsStoreOptions = {
    maxConcurrentUpdates: 10,
    updateAllProperties: false,
    syncMergeMoveLimit: 10_000,
    requestTimeoutMs: 3_000,
}

const CALLER_TAG = 'ingestion/personhog-store'

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
 * updates buffered as per-person lanes of folded ops the leader resolves
 * authoritatively. The cache holds BatchWritingPersonsCache's coherence
 * grade: a merge purges local state rather than repairing it, and a stale
 * view self-heals through the leader's tombstone redirect and re-reads.
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

    // The cache mirrors BatchWritingPersonsCache structure for structure,
    // with two differences the names carry: `projections` holds a whole
    // projected person rather than a PersonUpdate diff (the diffs live in
    // the lanes as raw ops for the leader), and `resolutions` is tri-state
    // (person key, null for known-absent, missing for never-resolved).

    /** ↔ distinctIdToPersonId. `${teamId}:${distinctId}` to a person key, or null for known-absent. */
    private resolutions: Map<string, string | null> = new Map()
    /**
     * ↔ personUpdateCache. The projected person per `${teamId}:${personId}`:
     * the last update-grade service answer with the lanes' folded ops
     * applied in place.
     */
    private projections: Map<string, InternalPerson> = new Map()
    /**
     * ↔ personCheckCache, keyed by person rather than distinct id.
     * Identity-resolve documents for repeat checking reads, kept apart so
     * the update path never trusts a document that lags the leader.
     */
    private personCheckCache: Map<string, InternalPerson> = new Map()
    /** ↔ batchDistinctKeys. Distinct keys each open batch referenced. */
    private batchDistinctKeys: Map<number, Set<string>> = new Map()
    /** ↔ distinctKeyRefCount. Batches per distinct key; zero at release evicts the key. */
    private distinctKeyRefCount: Map<string, number> = new Map()
    /**
     * The single staleness guard, with no Postgres counterpart: bumped on
     * every purge. A read stamps it before its first await and declines to
     * record on mismatch, so a response from before the purge cannot
     * refill what the purge dropped.
     */
    private teamGeneration: Map<number, number> = new Map()

    /** Serializes flush passes; see flush(). */
    private flushChain: Promise<void> = Promise.resolve()
    /** Total lane wait per flush, derived in the constructor from the transport retry budget. */
    private flushWaitBudgetMs: number

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
        if (!Number.isInteger(this.options.requestTimeoutMs) || this.options.requestTimeoutMs < 1) {
            throw new Error(`PERSONHOG_TIMEOUT_MS must be an integer >= 1, got ${this.options.requestTimeoutMs}`)
        }
        // A flush waits out a claimed lane rather than failing past it. The
        // wait outlasts one write's full transport retry budget, derived
        // rather than chosen so the two cannot drift apart; a holder writing
        // a deeper lane can still exhaust it, and that flush fails to
        // redelivery instead of acking over unwritten ops.
        this.flushWaitBudgetMs = (TRANSPORT_MAX_RETRIES + 1) * this.options.requestTimeoutMs + FLUSH_WAIT_ROUND_MS
    }

    forBatch(batchId: number): PersonsStoreForBatch {
        return new BatchBoundPersonsStore(this, batchId)
    }

    private generationOf(teamId: number): number {
        return this.teamGeneration.get(teamId) ?? 0
    }

    private bumpGeneration(teamId: number): void {
        this.teamGeneration.set(teamId, this.generationOf(teamId) + 1)
    }

    /** Callers get copies, so stamping a result cannot edit the shared cache. */
    private snapshot(person: InternalPerson): InternalPerson
    private snapshot(person: InternalPerson | null): InternalPerson | null
    private snapshot(person: InternalPerson | null): InternalPerson | null {
        return person === null ? null : { ...person, properties: { ...person.properties } }
    }

    /**
     * Undefined on miss. The update grade insists on a projection, whose
     * lineage is the leader's; check also accepts an identity document.
     */
    private getCachedPerson(
        teamId: number,
        distinctId: string,
        grade: 'check' | 'update'
    ): InternalPerson | null | undefined {
        const personKey = this.resolutions.get(`${teamId}:${distinctId}`)
        if (personKey === undefined) {
            return undefined
        }
        if (personKey === null) {
            return null
        }
        const projection = this.projections.get(personKey)
        if (projection !== undefined) {
            return this.snapshot(projection)
        }
        if (grade === 'check') {
            const checkDocument = this.personCheckCache.get(personKey)
            if (checkDocument !== undefined) {
                return this.snapshot(checkDocument)
            }
        }
        return undefined
    }

    /**
     * An edge moving off a person takes that person's documents with it:
     * over-eviction costs a re-read, an unnamed document is never freed.
     */
    private setDistinctIdToPersonId(distinctKey: string, personKey: string | null): void {
        const previous = this.resolutions.get(distinctKey)
        if (previous != null && previous !== personKey) {
            this.projections.delete(previous)
            this.personCheckCache.delete(previous)
        }
        this.resolutions.set(distinctKey, personKey)
    }

    /** Records this batch's reference to a distinct key for the release refcount. */
    private trackBatchEntry(batchId: number, distinctKey: string): void {
        let keys = this.batchDistinctKeys.get(batchId)
        if (!keys) {
            keys = new Set()
            this.batchDistinctKeys.set(batchId, keys)
        }
        if (!keys.has(distinctKey)) {
            keys.add(distinctKey)
            this.distinctKeyRefCount.set(distinctKey, (this.distinctKeyRefCount.get(distinctKey) ?? 0) + 1)
        }
    }

    /**
     * Frees an edge whose last batch released, and the mapped person's
     * documents with it; a sibling id still naming the person pays one
     * re-read, as under the Postgres cache.
     */
    private evictDistinctKey(distinctKey: string): void {
        const personKey = this.resolutions.get(distinctKey)
        if (personKey === undefined) {
            return
        }
        this.resolutions.delete(distinctKey)
        // A dirty lane keeps its documents; the Postgres cache defers this
        // eviction too.
        if (personKey !== null && !this.entries.get(personKey)?.segments.length) {
            this.projections.delete(personKey)
            this.personCheckCache.delete(personKey)
        }
    }

    /**
     * Strictly-newer wins on the version: reads can be delivered out of
     * order, and a projection carries folded ops an equal-version leader
     * document does not, so it must not roll them back.
     */
    private setCachedPersonForUpdate(personKey: string, doc: InternalPerson): void {
        const existing = this.projections.get(personKey)
        if (
            existing !== undefined &&
            typeof doc.version === 'number' &&
            typeof existing.version === 'number' &&
            doc.version <= existing.version
        ) {
            return
        }
        this.projections.set(personKey, this.snapshot(doc))
    }

    /** Any lane keeps its unsent ops; the next reader re-reads. */
    private clearPersonCacheForPersonId(personKey: string, reason: string): void {
        if (this.projections.delete(personKey)) {
            personhogStoreCachePurgeCounter.inc({ reason })
        }
        this.personCheckCache.delete(personKey)
    }

    /** The edge goes; the next touch re-resolves through identity. */
    private removeDistinctIdFromCache(teamId: number, distinctId: string, reason: string): void {
        if (this.resolutions.delete(`${teamId}:${distinctId}`)) {
            personhogStoreCachePurgeCounter.inc({ reason })
        }
    }

    /** The person's documents and every sibling id, named by the caller or not. */
    private clearAllCachesForPersonId(teamId: number, personId: string, reason: string): void {
        const personKey = `${teamId}:${personId}`
        for (const [distinctKey, mapped] of this.resolutions) {
            if (mapped === personKey) {
                this.resolutions.delete(distinctKey)
                personhogStoreCachePurgeCounter.inc({ reason })
            }
        }
        this.clearPersonCacheForPersonId(personKey, reason)
    }

    /**
     * Caches a fetch result and returns the view callers should see. A
     * generation moved by a purge means the answer predates it: served,
     * never cached.
     */
    private cacheFetchedPerson(
        teamId: number,
        distinctId: string,
        fetched: InternalPerson | null,
        batchId: number,
        options: { grade: 'check' | 'update'; generation: number; fillOnly?: boolean }
    ): InternalPerson | null {
        if (options.generation !== this.generationOf(teamId)) {
            return this.snapshot(fetched)
        }
        const distinctKey = `${teamId}:${distinctId}`
        if (fetched === null) {
            // A stale absence must not overwrite presence; a live mapping
            // stands and serves its best available view.
            const existing = this.resolutions.get(distinctKey)
            if (existing === undefined || existing === null) {
                this.setDistinctIdToPersonId(distinctKey, null)
                this.trackBatchEntry(batchId, distinctKey)
            }
            return existing != null ? (this.getCachedPerson(teamId, distinctId, options.grade) ?? null) : null
        }
        const personKey = `${teamId}:${fetched.id}`
        // A fill-only response can be arbitrarily late: it must not move a
        // standing edge, and it only fills a hole, because a standing
        // projection carries folds it cannot know about.
        const standingEdge = this.resolutions.get(distinctKey)
        if (options.fillOnly && standingEdge !== undefined) {
            if (standingEdge === personKey && !this.projections.has(personKey)) {
                this.setCachedPerson(personKey, fetched, options.grade)
            }
            return standingEdge !== null ? (this.getCachedPerson(teamId, distinctId, options.grade) ?? null) : null
        }
        this.setDistinctIdToPersonId(distinctKey, personKey)
        this.trackBatchEntry(batchId, distinctKey)
        this.setCachedPerson(personKey, fetched, options.grade)
        return this.getCachedPerson(teamId, distinctId, options.grade) ?? this.snapshot(fetched)
    }

    private setCachedPerson(personKey: string, doc: InternalPerson, grade: 'check' | 'update'): void {
        if (grade === 'update') {
            this.setCachedPersonForUpdate(personKey, doc)
            return
        }
        // A projection is at least as fresh as any identity answer.
        if (!this.projections.has(personKey)) {
            this.personCheckCache.set(personKey, this.snapshot(doc))
        }
    }

    /** Resolves through identity and uses that person directly, saving the leader hop. */
    async fetchForChecking(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const cached = this.getCachedPerson(teamId, distinctId, 'check')
        if (cached !== undefined) {
            return cached
        }
        const generation = this.generationOf(teamId)
        const [resolved] = await this.repository.resolvePersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        return this.cacheFetchedPerson(teamId, distinctId, resolved?.person ?? null, batchId, {
            grade: 'check',
            generation,
        })
    }

    /** Identity resolves the distinct id, then the leader supplies the freshest document. */
    async fetchForUpdate(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const cached = this.getCachedPerson(teamId, distinctId, 'update')
        if (cached !== undefined) {
            return cached
        }
        const generation = this.generationOf(teamId)
        const edge = this.resolutions.get(`${teamId}:${distinctId}`)
        if (edge != null) {
            // The edge is trusted but only a checking read backs it, which
            // lags the leader; the update path pays one leader read.
            const person = await this.repository.fetchPersonById(teamId, edge.slice(edge.indexOf(':') + 1), CALLER_TAG)
            return this.cacheFetchedPerson(teamId, distinctId, person, batchId, { grade: 'update', generation })
        }
        const [resolved] = await this.repository.resolvePersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        if (!resolved?.person) {
            return this.cacheFetchedPerson(teamId, distinctId, null, batchId, { grade: 'update', generation })
        }
        // A null read here means the person vanished mid-flight; the miss
        // is cached and the caller's create path re-resolves.
        const person = await this.repository.fetchPersonById(teamId, resolved.person.id, CALLER_TAG)
        return this.cacheFetchedPerson(teamId, distinctId, person, batchId, { grade: 'update', generation })
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
        const generation = this.generationOf(teamId)
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
            // leader read; a null means the person died mid-call, and the
            // redirect heals any ops folded onto identity's answer.
            const leaderDoc = await this.repository.fetchPersonById(teamId, person.id, CALLER_TAG)
            if (leaderDoc === null) {
                this.clearPersonCacheForPersonId(`${teamId}:${person.id}`, 'stale_write_answer')
                return { success: true, person: this.snapshot(person), messages: [], created }
            }
            person = leaderDoc
        }
        const recorded = this.cacheFetchedPerson(teamId, primaryDistinctId.distinctId, person, batchId, {
            grade: 'update',
            generation,
        })
        // Extras are never cached: the service can leave a conflicting
        // extra mapped to its existing person. No messages: the identity
        // service publishes its own on creation.
        return { success: true, person: recorded ?? this.snapshot(person), messages: [], created }
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
        const generation = this.generationOf(person.team_id)
        const target = await this.personNow(person, distinctId, batchId)
        return this.foldEventOps(target, ops, distinctId, batchId, generation)
    }

    /** The person this id belongs to now: a merge may have destroyed the caller's copy. */
    private async personNow(person: InternalPerson, distinctId: string, batchId: number): Promise<InternalPerson> {
        const resolved = this.getCachedPerson(person.team_id, distinctId, 'check')
        if (resolved) {
            return resolved
        }
        // An edge naming somebody else is the newer truth; one read
        // settles it, and a wrong fold heals through the redirect anyway.
        const edge = this.resolutions.get(`${person.team_id}:${distinctId}`)
        if (edge == null || edge === `${person.team_id}:${person.id}`) {
            return person
        }
        await this.fetchForUpdate(person.team_id, distinctId, batchId)
        return this.getCachedPerson(person.team_id, distinctId, 'check') ?? person
    }

    private foldEventOps(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string,
        batchId: number,
        generation: number
    ): [InternalPerson, PersonMessage[]] {
        // The caller's view, matching what Postgres would apply; the
        // leader's application at flush is the authoritative one.
        const refined = refineEventOps(ops, person.properties ?? {}, this.options.updateAllProperties, false)
        const [projected] = applyEventPropertyUpdates(refined, person)
        const scalarUpdates = computeOpsScalarUpdates(ops, projected)
        Object.assign(projected, scalarUpdates)

        const personKey = `${person.team_id}:${person.id}`
        this.referenceEntry(batchId, personKey)
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
            // Folding into a segment already on the wire would change the
            // payload underneath the write or lose this event.
            const folded = lastSegment === undefined || existing.inFlight ? null : foldOps(lastSegment, ops)
            if (folded === null) {
                existing.segments.push(ops)
            } else {
                existing.segments[last] = folded
            }
        }
        // Replaces the projection outright. A purge during personNow's read
        // outdates the view; the install declines and the next touch
        // re-resolves, while the lane keeps the ops.
        if (generation === this.generationOf(person.team_id)) {
            this.projections.set(personKey, this.snapshot(projected))
            this.setDistinctIdToPersonId(`${person.team_id}:${distinctId}`, personKey)
            this.trackBatchEntry(batchId, `${person.team_id}:${distinctId}`)
        }
        return [this.snapshot(projected), []]
    }

    /**
     * Runs the identity service's merge saga. Any verdict purges local
     * state for the merge's persons rather than repairing it; a call with
     * no verdict purges the same set and throws for the caller's bounded
     * retries.
     */
    async mergePersons(request: MergePersonsRequest, _batchId: number): Promise<MergePersonsResult> {
        const { teamId } = request
        const moveLimit = moveLimitFor(request.mergeMode, this.options.syncMergeMoveLimit)
        const opId = mergeOpIdFromRequest(
            teamId,
            request.eventUuid,
            request.targetDistinctId,
            request.sources.map((source) => source.distinctId),
            moveLimit
        )
        const namedIds = [request.targetDistinctId, ...request.sources.map((source) => source.distinctId)]
        // A stale edge can name a person the fresh resolve no longer
        // sees, and its lane still needs draining.
        const believed = namedIds
            .map((distinctId) => this.resolutions.get(`${teamId}:${distinctId}`))
            .filter((personKey): personKey is string => personKey != null)
        const resolved = await this.resolveMergeParticipants(teamId, namedIds)
        const affected = new Set<string>([...believed, ...resolved])
        await this.drainLanesBeforeMerge(teamId, [...affected], opId)

        let result
        try {
            result = await this.repository.mergePersons(
                {
                    teamId,
                    targetDistinctId: request.targetDistinctId,
                    sources: request.sources,
                    eventSet: request.eventOps.set,
                    eventSetOnce: request.eventOps.setOnce,
                    opId,
                    allowIdentifiedSources: request.allowIdentifiedSources,
                    moveLimit,
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
            // The saga may have run without answering; Postgres purges on
            // any merge throw too. Settled refusals get their own reason.
            const refused =
                error instanceof ConnectError &&
                (error.code === Code.InvalidArgument ||
                    error.metadata.get(SEMANTIC_REFUSAL_METADATA_KEY) === SEMANTIC_REFUSAL_OP_ID_REUSED)
            this.purgeAfterMerge(teamId, namedIds, affected, refused ? 'merge_refused' : 'merge_no_verdict')
            // A verdict: redelivery meets the same validation forever, so
            // it propagates raw rather than wedging the partition.
            if (error instanceof ConnectError && error.code === Code.InvalidArgument) {
                personhogStoreMergeCallFailedCounter.inc({ error: 'InvalidArgumentSettled' })
                throw error
            }
            // Deterministic and pre-durable, so raw. Keyed on the slug: a
            // refusal from a later saga step is a parked op, so it takes the
            // no-verdict path below, whose retries attach and resume it; if
            // they give up, the lifecycle sweeper settles it.
            if (
                error instanceof ConnectError &&
                error.metadata.get(SEMANTIC_REFUSAL_METADATA_KEY) === SEMANTIC_REFUSAL_OP_ID_REUSED
            ) {
                personhogStoreMergeCallFailedCounter.inc({ error: 'OpIdReusedSettled' })
                throw error
            }
            // No verdict, so an ack could lose the merge. Only the call is
            // wrapped, so a post-verdict bug surfaces as itself.
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
        const purgedPersons = new Set<string>(affected)
        for (const source of result.results) {
            if (source.sourcePersonId != null) {
                purgedPersons.add(`${teamId}:${source.sourcePersonId}`)
            }
        }
        if (result.survivor) {
            purgedPersons.add(`${teamId}:${result.survivor.id}`)
        }
        this.purgeAfterMerge(teamId, namedIds, purgedPersons, 'merge_verdict')
        // A fold that skipped or failed to settle any source aborts to the
        // sequential path, where each event gets its own durability
        // decision. The trigger id marks a fold request, so a single-pair
        // fold aborts the same way instead of dodging every guard.
        if (request.sources.length > 1 || request.triggerSourceDistinctId !== undefined) {
            const overLimit = result.results.some((source) => source.outcome === 'skipped_move_limit')
            const conflicted = result.results.some(
                (source) => source.outcome === 'skipped_conflict' || source.settled === false
            )
            const refused = result.results.some((source) => source.outcome === 'skipped_refused')
            // Error without a merged source can only be an abort, because
            // completion implies at least one source folded.
            const merged = result.results.some((source) => source.outcome === 'merged')
            const errored = !merged && result.results.some((source) => source.outcome === 'error')
            if (overLimit || conflicted || refused || errored) {
                return {
                    survivor: null,
                    results: [],
                    foldAborted: overLimit ? 'limit' : conflicted ? 'conflict' : refused ? 'refused' : 'error',
                }
            }
        }
        // A caller snapshot, never cached: the next touch re-reads.
        return {
            survivor: this.snapshot(result.survivor),
            results: result.results,
        }
    }

    /** One batched identity resolve of a merge's named ids, answering the person keys. */
    private async resolveMergeParticipants(teamId: number, distinctIds: string[]): Promise<Set<string>> {
        let resolved
        try {
            resolved = await this.repository.resolvePersonsByDistinctIds(
                distinctIds.map((distinctId) => ({ teamId, distinctId })),
                CALLER_TAG
            )
        } catch (error) {
            // Unwrapped it would reach the merge service's catch-all, which
            // acks the event with the merge lost.
            personhogStoreMergeDrainCounter.inc({ action: 'resolve_failed' })
            throw new PersonMergeCallFailedError(
                `personhog merge drain resolve failed: ${error instanceof Error ? error.message : String(error)}`,
                error
            )
        }
        const personKeys = new Set<string>()
        for (const entry of resolved) {
            if (entry.person) {
                personKeys.add(`${teamId}:${entry.person.id}`)
            }
        }
        return personKeys
    }

    /**
     * Writes every affected lane before the merge goes out, so buffered
     * source properties fold with source precedence, as Postgres reads
     * them through its cache.
     */
    private async drainLanesBeforeMerge(teamId: number, personKeys: string[], opId: string): Promise<void> {
        // Waiting out in-flight writers lets the drain capture their
        // lanes instead of skipping them.
        const inFlightWrites = personKeys
            .map((personKey) => this.entries.get(personKey)?.directWriteSettled)
            .filter((settled): settled is Promise<void> => settled !== undefined)
        if (inFlightWrites.length > 0) {
            await Promise.all(inFlightWrites)
        }
        const captured: CapturedLane[] = []
        for (const personKey of personKeys) {
            const entry = this.entries.get(personKey)
            if (!entry || entry.segments.length === 0) {
                continue
            }
            // A redirect owns the lane; its ops land after the merge.
            if (entry.inFlight) {
                personhogStoreMergeDrainCounter.inc({ action: 'lane_in_flight' })
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
            if (error instanceof PersonhogFencedError) {
                // Our own fence is an interrupted delivery of this same
                // merge; the saga call resumes it per op id.
                if (error.fencingOpId === opId) {
                    personhogStoreMergeDrainCounter.inc({ action: 'lane_fenced_own' })
                    continue
                }
                // The claim-race boundary the Postgres merge throws; the
                // service drops with a warning.
                personhogStoreMergeDrainCounter.inc({ action: 'lane_claimed' })
                throw new PersonClaimedByLifecycleOpError(
                    `person held by lifecycle op ${error.fencingOpId ?? 'unknown'} during a merge drain`,
                    teamId
                )
            }
            // The typed wrapper reaches the merge service's bounded retries.
            throw new PersonMergeCallFailedError(
                `personhog pre-merge write failed: ${error instanceof Error ? error.message : String(error)}`,
                error
            )
        }
    }

    /**
     * Every named id, affected person, and sibling id leaves the cache
     * under one generation bump. Lanes are kept: a destroyed person's ops
     * reach the survivor through the redirect, as they do under Postgres.
     */
    private purgeAfterMerge(teamId: number, distinctIds: string[], personKeys: Set<string>, reason: string): void {
        for (const personKey of personKeys) {
            this.clearAllCachesForPersonId(teamId, personKey.slice(personKey.indexOf(':') + 1), reason)
        }
        for (const distinctId of distinctIds) {
            this.removeDistinctIdFromCache(teamId, distinctId, reason)
        }
        this.bumpGeneration(teamId)
    }

    /** The leader enforces the size ceiling at admission; there is nothing to measure here. */
    personPropertiesSize(_personId: string, _teamId: number): Promise<number> {
        return Promise.resolve(0)
    }

    getFlushStats(): BatchWritingStoreFlushStats {
        return {
            dirtyEntryCount: [...this.entries.values()].filter((entry) => entry.segments.length > 0).length,
            referencedBatchCount: this.batchEntryKeys.size,
            cacheEntryCount: this.projections.size,
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
        distinctId: string,
        batchId: number,
        forceUpdate?: boolean,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        const unsupported = Object.keys(otherUpdates).filter((key) => key !== 'is_identified' && key !== 'last_seen_at')
        if (unsupported.length > 0) {
            // One count per field bounds the label by the schema.
            for (const field of unsupported) {
                personhogStoreUnsupportedFieldCounter.labels({ field }).inc()
            }
            throw new PersonhogUnsupportedFieldError(unsupported)
        }
        const generation = this.generationOf(person.team_id)
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
            // past what we held; without an applied write it is a no-op.
            if (applied) {
                this.clearPersonCacheForPersonId(personKey, 'stale_write_answer')
            }
            return [person, [], false]
        }
        // A generation moved by a purge means this answer predates it.
        if (generation === this.generationOf(person.team_id)) {
            this.setDistinctIdToPersonId(`${person.team_id}:${distinctId}`, personKey)
            this.trackBatchEntry(batchId, `${person.team_id}:${distinctId}`)
            this.setCachedPersonForUpdate(personKey, updated)
        }
        // No ClickHouse message: the leader's changelog is the person feed.
        return [this.snapshot(updated), [], false]
    }

    /**
     * The update fetch's two-step done once for the whole batch, so
     * per-event processing hits the cache. Best-effort.
     */
    async prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void> {
        const seen = new Set<string>()
        const unresolved = teamDistinctIds.filter((entry) => {
            const key = `${entry.teamId}:${entry.distinctId}:${entry.batchId}`
            if (seen.has(key)) {
                return false
            }
            seen.add(key)
            return this.getCachedPerson(entry.teamId, entry.distinctId, 'check') === undefined
        })
        if (unresolved.length === 0) {
            return
        }
        const generations = new Map<number, number>()
        for (const entry of unresolved) {
            this.prefetchingBatches.add(entry.batchId)
            if (!generations.has(entry.teamId)) {
                generations.set(entry.teamId, this.generationOf(entry.teamId))
            }
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
                        const generation = generations.get(entry.teamId) ?? 0
                        // Caching for a released batch recreates its key
                        // set, and nothing ever releases it again.
                        if (!this.prefetchingBatches.has(batchId)) {
                            return
                        }
                        if (!entry.person) {
                            this.cacheFetchedPerson(entry.teamId, entry.distinctId, null, batchId, {
                                grade: 'check',
                                generation,
                            })
                            return
                        }
                        const person = await this.repository.fetchPersonById(entry.teamId, entry.person.id, CALLER_TAG)
                        if (!this.prefetchingBatches.has(batchId)) {
                            return
                        }
                        // Fill-only: this response raced everything the
                        // batch did since the request went out.
                        this.cacheFetchedPerson(entry.teamId, entry.distinctId, person, batchId, {
                            grade: 'update',
                            generation,
                            fillOnly: true,
                        })
                    })
                )
            )
        } catch (error) {
            // Counted because the degradation reads as latency.
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
        // Success lets the batch ack, so the pass must not return while any
        // lane holds unwritten segments: claimed lanes are waited out and
        // rewritten, or the pass fails and the batch redelivers.
        for (let round = 0; ; round++) {
            const pass = { deferrals: 0 }
            await this.writeEligibleLanes(pass)
            if (pass.deferrals === 0) {
                // No FlushResults: the leader's changelog is the person
                // feed, so a flush publishes nothing.
                return []
            }
            if (round * FLUSH_WAIT_ROUND_MS >= this.flushWaitBudgetMs) {
                personhogStoreFlushCounter.inc({ outcome: 'parked_exhausted' })
                throw new Error(
                    `flush cannot complete: ${pass.deferrals} lanes deferred behind writes that did not settle`
                )
            }
            // Bounded, so a wedged writer exhausts the rounds instead of
            // hanging the flush past the consumer's poll budget.
            const settles = [...this.entries.values()]
                .filter((entry) => entry.segments.length > 0)
                .map((entry) => entry.directWriteSettled)
                .filter((settled): settled is Promise<void> => settled !== undefined)
            let timer: NodeJS.Timeout | undefined
            try {
                // A redirect-owned deferral has no settle; the round still
                // waits out the timer rather than racing an empty set.
                const roundTimer = new Promise<void>((resolve) => {
                    timer = setTimeout(resolve, FLUSH_WAIT_ROUND_MS)
                })
                await (settles.length > 0 ? Promise.race([Promise.allSettled(settles), roundTimer]) : roundTimer)
            } finally {
                clearTimeout(timer)
            }
        }
    }

    private async writeEligibleLanes(pass: { deferrals: number }): Promise<void> {
        // No await in this block, so the claim snapshot is atomic.
        const captured: CapturedLane[] = []
        for (const [personKey, entry] of this.entries) {
            if (entry.segments.length === 0) {
                continue
            }
            // Another writer holds the lane; the round loop waits it out.
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

    /** Runs on every exit from a write; a mark left set would strand the ops. */
    private releaseWritten(personKey: string, entry: OpsLaneEntry): void {
        entry.inFlight = false
        entry.settleWrite?.()
        entry.settleWrite = undefined
        entry.directWriteSettled = undefined
        if (entry.segments.length > 0) {
            // The settle is the last hand holding an abandoned entry.
            if (entry.abandoned && !this.entryHeldByAnyBatch(personKey) && this.entries.get(personKey) === entry) {
                personhogStoreShadowShedCounter.inc(entry.segments.length)
                entry.segments.length = 0
                this.entries.delete(personKey)
                this.clearPersonCacheForPersonId(personKey, 'lane_retired')
            }
            return
        }
        // Identity-guarded: a stale finalizer must not retire a recreated entry.
        if (!this.entryHeldByAnyBatch(personKey) && this.entries.get(personKey) === entry) {
            this.entries.delete(personKey)
            // Evictions defer the document drop to a dirty lane; it lands here.
            this.clearPersonCacheForPersonId(personKey, 'lane_retired')
        }
    }

    private async writeEntry(personKey: string, entry: OpsLaneEntry, segments: number): Promise<void> {
        try {
            // What this pass owes; the array length is no substitute, since
            // folds arriving mid-redirect inflate it.
            const progress = { remaining: segments }
            // Every iteration writes the remainder, drops a unit, or
            // throws; the redirect budget fails a fast-merging lineage to
            // redelivery rather than chasing it forever.
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
                        // Merged or deleted since the fold; the lane is
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
                        // and the loop writes the remainder; the log covers
                        // the leader's per-team-throttled customer warning.
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
                    if (error instanceof PersonhogFencedError) {
                        // Expected coordination, so it stays off the error
                        // series an alert would page on: the holder settles
                        // and redelivery flows.
                        personhogStoreFlushCounter.inc({ outcome: 'fenced' })
                        logger.warn('flush bounced on a lifecycle fence; the batch redelivers', {
                            teamId: entry.teamId,
                            personId: entry.personId,
                            fencingOpId: error.fencingOpId,
                        })
                    } else {
                        if (!(error instanceof CountedRedirectError)) {
                            personhogStoreFlushCounter.inc({ outcome: 'error' })
                            personhogStoreFlushErrorCounter.inc({ error: errorClassLabel(error) })
                        }
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
     * Writes a lane's leading segments, removing each as it lands. The
     * answers are not cached: the projection already carries every folded
     * op, and the leader's refinement arrives on the next re-read.
     */
    private async writeSegments(entry: OpsLaneEntry, personId: string, progress: { remaining: number }): Promise<void> {
        const count = Math.min(progress.remaining, entry.segments.length)
        for (let written = 0; written < count; written++) {
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
            // A null answer without a throw means the write applied and
            // the leader moved past what we held. Redirect writes are
            // excluded: the redirect purges the survivor itself.
            if (personId === entry.personId && answer === null) {
                this.clearPersonCacheForPersonId(`${entry.teamId}:${personId}`, 'stale_write_answer')
            }
        }
    }

    /**
     * Re-resolves a vanished person's distinct id and writes to whoever
     * owns it now, matching the Postgres merged-away recovery. One resolve
     * is enough: the saga repoints mappings before the leader answers a
     * tombstone, and no owner means a genuine delete.
     */
    private async redirectToSurvivor(entry: OpsLaneEntry, progress: { remaining: number }): Promise<void> {
        const generation = this.generationOf(entry.teamId)
        const [resolved] = await this.repository.resolvePersonsByDistinctIds(
            [{ teamId: entry.teamId, distinctId: entry.distinctId }],
            CALLER_TAG
        )
        const survivorId = resolved?.person?.id
        if (survivorId === undefined || survivorId === entry.personId) {
            // Released, so the redelivered events re-resolve rather than
            // folding onto the corpse again.
            this.removeDistinctIdFromCache(entry.teamId, entry.distinctId, 'redirect_gone')
            this.clearPersonCacheForPersonId(`${entry.teamId}:${entry.personId}`, 'redirect_gone')
            personhogStoreFlushCounter.inc({ outcome: 'redirect_gone' })
            throw new CountedRedirectError(
                `person ${entry.personId} in team ${entry.teamId} vanished and ${entry.distinctId} resolves to ` +
                    `${survivorId === undefined ? 'nobody' : 'the same person'}; failing the flush to redeliver`
            )
        }
        // The resolve proved where the id belongs, so heal the edge, the
        // repoint the Postgres cache performs too. Skipped when a purge
        // moved the generation (this answer predates it), and for a key no
        // batch recorded (a mapping nothing would ever release).
        if (generation === this.generationOf(entry.teamId)) {
            const distinctKey = `${entry.teamId}:${entry.distinctId}`
            if (this.resolutions.has(distinctKey)) {
                this.setDistinctIdToPersonId(distinctKey, `${entry.teamId}:${survivorId}`)
            }
        }
        this.clearPersonCacheForPersonId(`${entry.teamId}:${entry.personId}`, 'redirect_survivor')
        // Ops travel as they stand, deletions included, matching Postgres.
        await this.writeSegments(entry, survivorId, progress)
        // The survivor's projection cannot know about these ops.
        this.clearPersonCacheForPersonId(`${entry.teamId}:${survivorId}`, 'redirect_survivor')
    }

    /** An entry still holding unwritten ops outlives its last reference. */
    releaseBatch(batchId: number): void {
        // Any prefetch still on the wire answers into nothing from here on.
        this.prefetchingBatches.delete(batchId)
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
            this.entries.delete(personKey)
        }
        this.releaseBatchId(batchId)
    }

    /**
     * The shadow valve: a shadow flush failure cannot fail the batch, so
     * unwritten segments only this batch was keeping are shed and counted
     * rather than growing without bound through an outage.
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
                // The flag hands the shed to the write's settle instead of
                // zeroing segments under it.
                entry.abandoned = true
                continue
            }
            if (entry && entry.segments.length > 0) {
                personhogStoreShadowShedCounter.inc(entry.segments.length)
                entry.segments.length = 0
            }
            this.entries.delete(personKey)
        }
        this.releaseBatchId(batchId)
    }

    /** Drops a batch's distinct-key references, freeing edges no other batch holds. */
    private releaseBatchId(batchId: number): void {
        const keys = this.batchDistinctKeys.get(batchId)
        this.batchDistinctKeys.delete(batchId)
        for (const distinctKey of keys ?? []) {
            const refs = (this.distinctKeyRefCount.get(distinctKey) ?? 1) - 1
            if (refs > 0) {
                this.distinctKeyRefCount.set(distinctKey, refs)
                continue
            }
            this.distinctKeyRefCount.delete(distinctKey)
            this.evictDistinctKey(distinctKey)
        }
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

    /** A scan, not a counter: batches number in the handful and a counter can drift. */
    private entryHeldByAnyBatch(personKey: string): boolean {
        for (const keys of this.batchEntryKeys.values()) {
            if (keys.has(personKey)) {
                return true
            }
        }
        return false
    }

    shutdown(): Promise<void> {
        // The data is redelivery-safe; the drain-order bug must be loud.
        const unwritten = [...this.entries.values()].filter((entry) => entry.segments.length > 0).length
        if (unwritten > 0) {
            return Promise.reject(
                new Error(`PersonhogPersonsStore shut down with ${unwritten} lanes holding unwritten ops`)
            )
        }
        return Promise.resolve()
    }
}
