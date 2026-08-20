import { DateTime } from 'luxon'
import pLimit from 'p-limit'
import { Counter } from 'prom-client'

import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogPropertiesSizeError } from '~/common/personhog/persons'
import { PersonMessage } from '~/common/persons/person-message'
import { InternalPersonWithDistinctId, LifecycleMarkPerson } from '~/common/persons/repositories/person-repository'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult, MoveDistinctIdsResult } from '~/common/utils/db/db'
import { logger } from '~/common/utils/logger'
import { NoRowsUpdatedError } from '~/common/utils/utils'
import { BatchWritingStoreFlushStats } from '~/ingestion/common/stores/batch-writing-store'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'

import { EventOps, applyEventPropertyUpdates, computeOpsScalarUpdates, foldOps, refineEventOps } from './person-update'
import { FlushResult, PersonsStore } from './persons-store'
import { BatchBoundPersonsStore, PersonsStoreForBatch } from './persons-store-for-batch'
import { PersonsStoreTransaction } from './persons-store-transaction'

export const personhogStoreFlushCounter = new Counter({
    name: 'personhog_store_flush_ops_total',
    help: 'Folded person updates flushed to the personhog leader, by outcome',
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
}

const DEFAULT_OPTIONS: PersonhogPersonsStoreOptions = {
    maxConcurrentUpdates: 10,
    updateAllProperties: false,
}

const CALLER_TAG = 'ingestion/personhog-store'

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

interface OpsLaneEntry {
    teamId: number
    personId: string
    distinctId: string
    /**
     * Folded ops in arrival order. Almost always one segment; a new one
     * starts only when foldOps cannot represent the composition, and
     * flush ships segments sequentially so the leader refines between
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
}

/**
 * The personhog implementation of the person store: distinct-id
 * resolution and person creation through the identity service's
 * get-or-create, person state through the leader's strong reads, and
 * property updates as raw op folds shipped to the leader, which refines
 * them against authoritative state under the per-person lock.
 *
 * Where the Postgres store refines ops against a fetched snapshot before
 * writing, this store ships them as stated, so no version-race machinery
 * exists here. Fetches memoize per batch; folded ops accumulate per
 * (batch, person) and flush as one call per person.
 *
 * Person uuids derive deterministically from team_id:distinct_id on the
 * identity service; the uuid argument to createPerson is advisory and
 * the returned person carries the authoritative one.
 */
export class PersonhogPersonsStore implements PersonsStore {
    private options: PersonhogPersonsStoreOptions
    /** Folded ops per batch, keyed by `${teamId}:${personId}`. */
    private lanes: Map<number, Map<string, OpsLaneEntry>> = new Map()
    /**
     * Distinct-id resolution per batch: `${teamId}:${distinctId}` to the
     * person key, or null for a known-absent id. Split from person state
     * so every distinct id of a person reads the same pending
     * projection, not just the one that triggered the update.
     */
    private resolutions: Map<number, Map<string, string | null>> = new Map()
    /**
     * Person state per batch, keyed by `${teamId}:${personId}`. Once ops
     * fold for a person this holds the pending projection (the batch's
     * read-your-write view), and fetches must not clobber it with
     * service state.
     */
    private personState: Map<number, Map<string, InternalPerson>> = new Map()
    /** Serializes flush passes; see flush(). */
    private flushChain: Promise<void> = Promise.resolve()

    constructor(
        private repository: PersonHogPersonWriteRepository,
        options?: Partial<PersonhogPersonsStoreOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
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
        const cached = this.lookupMemo(teamId, distinctId, batchId)
        if (cached !== undefined) {
            return cached
        }
        const [resolved] = await this.repository.resolvePersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        return this.recordFetch(teamId, distinctId, resolved?.person ?? null, batchId)
    }

    /**
     * Update reads split resolution from state: identity resolves the
     * distinct id on the primary, then the person's state comes from the
     * partition leader, which the primary lags by writer apply lag. The
     * projection this feeds enriches the batch's events, so the baseline
     * must be the leader's.
     */
    async fetchForUpdate(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const cached = this.lookupMemo(teamId, distinctId, batchId)
        if (cached !== undefined) {
            return cached
        }
        const [resolved] = await this.repository.resolvePersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        if (!resolved?.person) {
            return this.recordFetch(teamId, distinctId, null, batchId)
        }
        // A null here means the person vanished between resolve and read
        // (merged or deleted mid-flight); record the resolution miss and
        // let the caller's create path re-resolve authoritatively.
        const person = await this.repository.fetchPersonById(teamId, resolved.person.id, CALLER_TAG)
        return this.recordFetch(teamId, distinctId, person, batchId)
    }

    async fetchPersonsForUpdateByDistinctIds(
        teamId: number,
        distinctIds: string[],
        batchId: number
    ): Promise<InternalPersonWithDistinctId[]> {
        const resolved = await this.repository.resolvePersonsByDistinctIds(
            distinctIds.map((distinctId) => ({ teamId, distinctId })),
            CALLER_TAG
        )
        const limit = pLimit(this.options.maxConcurrentUpdates)
        const fetched = await Promise.all(
            resolved.map((entry) =>
                limit(async () => {
                    if (!entry.person) {
                        this.recordFetch(teamId, entry.distinctId, null, batchId)
                        return null
                    }
                    const person = await this.repository.fetchPersonById(teamId, entry.person.id, CALLER_TAG)
                    // Pending projections win over fetched state here
                    // too, so the merge planner reads the same pre-flush
                    // view the update path does.
                    const recorded = this.recordFetch(teamId, entry.distinctId, person, batchId)
                    if (!recorded) {
                        return null
                    }
                    return { ...recorded, distinct_id: entry.distinctId } as InternalPersonWithDistinctId
                })
            )
        )
        return fetched.filter((person): person is InternalPersonWithDistinctId => person !== null)
    }

    /** Resolves a distinct id through the batch memos, undefined on miss. */
    private lookupMemo(teamId: number, distinctId: string, batchId: number): InternalPerson | null | undefined {
        const resolution = this.resolutionMemo(batchId).get(`${teamId}:${distinctId}`)
        if (resolution === undefined) {
            return undefined
        }
        if (resolution === null) {
            return null
        }
        return this.personStateMemo(batchId).get(resolution) ?? undefined
    }

    /**
     * Records a fetch result in the batch memos and returns the state
     * callers should see: an existing pending projection wins over the
     * fetched snapshot, so a fetch never rolls the batch's view back to
     * pre-update state.
     */
    private recordFetch(
        teamId: number,
        distinctId: string,
        fetched: InternalPerson | null,
        batchId: number
    ): InternalPerson | null {
        const resolutions = this.resolutionMemo(batchId)
        if (fetched === null) {
            // Never downgrade a live mapping: a stale prefetch response
            // can land after the batch created or resolved this person,
            // and absence must not overwrite presence.
            const existing = resolutions.get(`${teamId}:${distinctId}`)
            if (existing === undefined || existing === null) {
                resolutions.set(`${teamId}:${distinctId}`, null)
            }
            return existing != null ? (this.personStateMemo(batchId).get(existing) ?? null) : null
        }
        const personKey = `${teamId}:${fetched.id}`
        resolutions.set(`${teamId}:${distinctId}`, personKey)
        const state = this.personStateMemo(batchId)
        const hasPending = this.lanes.get(batchId)?.has(personKey) ?? false
        if (!hasPending || !state.has(personKey)) {
            state.set(personKey, fetched)
        }
        return state.get(personKey) ?? fetched
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
        const { person, created } = await this.repository.getOrCreatePersonByDistinctId(
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
        const personKey = `${teamId}:${person.id}`
        const resolutions = this.resolutionMemo(batchId)
        resolutions.set(`${teamId}:${primaryDistinctId.distinctId}`, personKey)
        for (const extra of extraDistinctIds ?? []) {
            resolutions.set(`${teamId}:${extra.distinctId}`, personKey)
        }
        this.personStateMemo(batchId).set(personKey, person)
        // The identity service publishes its own downstream messages on
        // the creation branch, so none are surfaced here.
        return { success: true, person, messages: [], created }
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

        // A local projection for the caller: the same application the
        // Postgres world would perform, so the processor returns a
        // sensible person. The leader's application at flush remains the
        // authoritative one for this world.
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

        const lane = this.opsLane(batchId)
        const personKey = `${person.team_id}:${person.id}`
        const existing = lane.get(personKey)
        if (!existing) {
            lane.set(personKey, {
                teamId: person.team_id,
                personId: person.id,
                distinctId,
                segments: [ops],
                triggersUpdate,
            })
        } else {
            existing.triggersUpdate = existing.triggersUpdate || triggersUpdate
            const last = existing.segments.length - 1
            const folded = foldOps(existing.segments[last], ops)
            if (folded === null) {
                existing.segments.push(ops)
            } else {
                existing.segments[last] = folded
            }
        }
        // The memo now holds the pending projection: every distinct id
        // resolving to this person sees the change pre-flush, and the
        // next event composes on top. Merged properties are computed
        // from the projection, so pending ops travel to the merge
        // target through it.
        this.personStateMemo(batchId).set(personKey, projected)
        this.resolutionMemo(batchId).set(`${person.team_id}:${distinctId}`, personKey)
        return Promise.resolve([projected, []])
    }

    // Deletes exist only to destroy the losing persons of a merge, and
    // the shadow gates merge events off this store; once merges move to
    // personhog, the merge saga owns those deletions end to end, so no
    // store-level delete path will ever be needed here.
    /**
     * The personhog world has no Postgres transactions; transaction
     * semantics for routed deployments live in the routing store, which
     * never delegates this member. Reaching it is a wiring bug.
     */
    inTransaction<T>(_description: string, _transaction: (tx: PersonsStoreTransaction) => Promise<T>): Promise<T> {
        return Promise.reject(new PersonhogPendingRpcError('inTransaction', 'merge saga'))
    }

    // Merge execution is the merge saga's once it lands; until then every
    // mutation in the family is a loud placeholder.

    updatePersonForMerge(
        _person: InternalPerson,
        _update: Partial<InternalPerson>,
        _distinctId: string,
        _batchId: number,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return Promise.reject(new PersonhogPendingRpcError('updatePersonForMerge', 'merge saga'))
    }

    claimLifecycleMarks(
        _opId: string,
        _teamId: number,
        _persons: LifecycleMarkPerson[],
        _distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return Promise.reject(new PersonhogPendingRpcError('claimLifecycleMarks', 'merge saga'))
    }

    releaseLifecycleMarks(
        _opId: string,
        _teamId: number,
        _distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return Promise.reject(new PersonhogPendingRpcError('releaseLifecycleMarks', 'merge saga'))
    }

    isPersonLive(_person: InternalPerson, _distinctId: string, _tx?: PersonRepositoryTransaction): Promise<boolean> {
        return Promise.reject(new PersonhogPendingRpcError('isPersonLive', 'merge saga'))
    }

    addDistinctId(
        _person: InternalPerson,
        _distinctId: string,
        _version: number,
        _tx: PersonRepositoryTransaction | undefined,
        _batchId: number
    ): Promise<PersonMessage[]> {
        return Promise.reject(new PersonhogPendingRpcError('addDistinctId', 'merge saga'))
    }

    moveDistinctIds(
        _source: InternalPerson,
        _target: InternalPerson,
        _distinctId: string,
        _limit: number | undefined,
        _tx: PersonRepositoryTransaction,
        _batchId: number
    ): Promise<MoveDistinctIdsResult> {
        return Promise.reject(new PersonhogPendingRpcError('moveDistinctIds', 'merge saga'))
    }

    moveDistinctIdsFromPersons(
        _sources: InternalPerson[],
        _target: InternalPerson,
        _distinctId: string,
        _tx: PersonRepositoryTransaction,
        _batchId: number
    ): Promise<MoveDistinctIdsResult> {
        return Promise.reject(new PersonhogPendingRpcError('moveDistinctIdsFromPersons', 'merge saga'))
    }

    // Postgres bookkeeping with nothing to answer in this world: shadow
    // teams are fresh, so no cohort rows or hash-key overrides exist to
    // fix up.

    updateCohortsAndFeatureFlagsForMerge(
        _teamID: Team['id'],
        _sourcePersonID: InternalPerson['id'],
        _targetPersonID: InternalPerson['id'],
        _distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return Promise.resolve()
    }

    updateCohortsAndFeatureFlagsForMergeBatch(
        _teamID: Team['id'],
        _sourcePersonIDs: InternalPerson['id'][],
        _targetPersonID: InternalPerson['id'],
        _distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<void> {
        return Promise.resolve()
    }

    /** The leader enforces the size ceiling at admission; there is nothing to measure here. */
    personPropertiesSize(_personId: string, _teamId: number): Promise<number> {
        return Promise.resolve(0)
    }

    getFlushStats(): BatchWritingStoreFlushStats {
        let dirtyEntryCount = 0
        for (const lane of this.lanes.values()) {
            dirtyEntryCount += lane.size
        }
        let cacheEntryCount = 0
        for (const memo of this.personState.values()) {
            cacheEntryCount += memo.size
        }
        return { dirtyEntryCount, referencedBatchCount: this.lanes.size, cacheEntryCount }
    }

    deletePersons(
        _persons: InternalPerson[],
        _distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<PersonMessage[]> {
        return Promise.reject(new PersonhogPendingRpcError('deletePersons', 'merge saga'))
    }

    deletePerson(
        _person: InternalPerson,
        _distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<PersonMessage[]> {
        return Promise.reject(new PersonhogPendingRpcError('deletePerson', 'merge saga'))
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
        // No ClickHouse message: the leader's changelog is this world's
        // person feed, so emitting here would double-publish.
        return [updated, [], false]
    }

    /**
     * Counts by fetching: the RPC surface has no dedicated count, and the
     * merge pre-check consuming this runs at shadow-team scale, where
     * fetching the ids to count them is acceptable. Absent persons count
     * zero, matching the SQL count.
     */
    async countDistinctIdsForPersons(
        teamId: Team['id'],
        personIds: InternalPerson['id'][],
        _distinctId: string,
        _tx: PersonRepositoryTransaction
    ): Promise<Map<string, number>> {
        const byPerson = await this.repository.getDistinctIdsForPersons(teamId, personIds, undefined, CALLER_TAG)
        return new Map(personIds.map((id) => [id, byPerson[id]?.length ?? 0]))
    }

    async fetchPersonDistinctIds(
        person: InternalPerson,
        _distinctId: string,
        limit: number | undefined,
        _tx: PersonRepositoryTransaction
    ): Promise<string[]> {
        const byPerson = await this.repository.getDistinctIdsForPersons(person.team_id, [person.id], limit, CALLER_TAG)
        return byPerson[person.id] ?? []
    }

    removeDistinctIdFromCache(teamId: number, distinctId: string): void {
        // Resolution only: the person's state may still be valid under
        // its other distinct ids; what a merge changed is which person
        // this id maps to, and the next fetch re-resolves it.
        const key = `${teamId}:${distinctId}`
        for (const memo of this.resolutions.values()) {
            memo.delete(key)
        }
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
            return this.lookupMemo(entry.teamId, entry.distinctId, entry.batchId) === undefined
        })
        if (unresolved.length === 0) {
            return
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
                        if (!entry.person) {
                            this.recordFetch(entry.teamId, entry.distinctId, null, batchId)
                            return
                        }
                        const person = await this.repository.fetchPersonById(entry.teamId, entry.person.id, CALLER_TAG)
                        this.recordFetch(entry.teamId, entry.distinctId, person, batchId)
                    })
                )
            )
        } catch (error) {
            logger.warn('personhog prefetch failed; resolution falls back to first touch', { error })
        }
    }

    /**
     * Ships every batch's folded lanes to the leader, one entry per
     * person, segments in order. There is deliberately no Postgres
     * fallback. A missing person (deleted or merged mid-batch) and the
     * leader's size rejection are counted and skipped, since neither can
     * succeed on retry, but segments already applied still publish.
     * Publication gates on the version floor rather than the last
     * response's no-change flag: a retried call whose lost first attempt
     * landed replays into the leader's no-change fast path, and the
     * version still tells the truth. Any other failure fails the flush
     * so the batch retries whole.
     *
     * Passes serialize, one at a time, with later calls queueing behind
     * the running one. A pass claims a synchronous snapshot of every
     * lane before shipping, so ops folded mid-pass land in fresh entries
     * and ship on the next pass, never into an entry already in flight.
     * A failed ship restores its entry, ahead of anything folded since:
     * the failing flush call fails its own batch, but the entry may
     * belong to a sibling batch that never acked its events, and folds
     * are idempotent, so re-shipping on a later pass is safe.
     *
     * A lane entry with no update-worthy change — every refined change
     * filtered, nothing forced, no scalar movement — is suppressed here
     * rather than shipped, the same no-op classification the Postgres
     * store applies at its flush. The exception is a person a sibling
     * batch also holds ops for: the no-change verdict was judged against
     * this batch's own baseline, so the entry ships instead and the
     * leader's refinement no-ops it if it truly is one.
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
        const captured: { batchId: number; personKey: string; entry: OpsLaneEntry }[] = []
        for (const [batchId, lane] of this.lanes) {
            for (const [personKey, entry] of lane) {
                captured.push({ batchId, personKey, entry })
            }
        }
        // One entry per person per lane, so the number of captured
        // entries for a person is the number of batches holding it.
        const entriesPerPerson = new Map<string, number>()
        for (const { personKey } of captured) {
            entriesPerPerson.set(personKey, (entriesPerPerson.get(personKey) ?? 0) + 1)
        }
        for (const { batchId, personKey } of captured) {
            this.lanes.get(batchId)?.delete(personKey)
        }
        const limit = pLimit(this.options.maxConcurrentUpdates)
        const outcomes = await Promise.allSettled(
            captured.map(({ batchId, personKey, entry }) =>
                limit(() => this.shipEntry(batchId, personKey, entry, (entriesPerPerson.get(personKey) ?? 0) > 1))
            )
        )
        for (const [batchId, lane] of this.lanes) {
            if (lane.size === 0) {
                this.lanes.delete(batchId)
            }
        }
        const failed = outcomes.find((outcome): outcome is PromiseRejectedResult => outcome.status === 'rejected')
        if (failed) {
            throw failed.reason
        }
        // No FlushResults: the leader's changelog is the ClickHouse
        // person feed, so a flush publishes nothing — shipping the
        // segments is the whole job.
        return []
    }

    private async shipEntry(
        batchId: number,
        personKey: string,
        entry: OpsLaneEntry,
        siblingPending: boolean
    ): Promise<void> {
        if (!entry.triggersUpdate && !siblingPending) {
            personhogStoreFlushCounter.inc({ outcome: 'filtered' })
            return
        }
        try {
            for (const ops of entry.segments) {
                await this.repository.updatePersonProperties(
                    {
                        teamId: entry.teamId,
                        personId: entry.personId,
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
            personhogStoreFlushCounter.inc({ outcome: 'success' })
        } catch (error) {
            if (error instanceof NoRowsUpdatedError) {
                // The person was merged or deleted since the fold.
                // In-batch that is fine: the merge carried the pending
                // projection to its target. Merge events are gated off
                // this store, so this counter firing means a bug, not a
                // cross-batch race.
                personhogStoreFlushCounter.inc({ outcome: 'not_found' })
            } else if (error instanceof PersonhogPropertiesSizeError) {
                // Counted only: the store holds no outputs handle, so
                // the size-violation ingestion warning the Postgres
                // store emits has no path from here.
                personhogStoreFlushCounter.inc({ outcome: 'size_violation' })
            } else {
                personhogStoreFlushCounter.inc({ outcome: 'error' })
                logger.error('Failed to flush folded update to personhog', {
                    teamId: entry.teamId,
                    personId: entry.personId,
                    error,
                })
                this.restoreEntry(batchId, personKey, entry)
                throw error
            }
        }
    }

    /**
     * Puts a failed entry back in its lane, its segments ahead of any
     * folded since the pass claimed it, preserving order for the next
     * pass. A released batch stays released: its redelivery re-folds
     * these ops.
     */
    private restoreEntry(batchId: number, personKey: string, entry: OpsLaneEntry): void {
        const lane = this.lanes.get(batchId)
        if (!lane) {
            return
        }
        const newer = lane.get(personKey)
        if (!newer) {
            lane.set(personKey, entry)
            return
        }
        newer.segments = [...entry.segments, ...newer.segments]
        newer.triggersUpdate = newer.triggersUpdate || entry.triggersUpdate
    }

    /**
     * Frees a completed batch's resolution memo and any unfetched lane,
     * mirroring the Postgres store's post-flush release in
     * flush-batch-stores-step. No reference counting: unlike the
     * Postgres cache, nothing here is shared across batches.
     */
    releaseBatch(batchId: number): void {
        this.resolutions.delete(batchId)
        this.personState.delete(batchId)
        this.lanes.delete(batchId)
    }

    shutdown(): Promise<void> {
        return Promise.resolve()
    }

    private opsLane(batchId: number): Map<string, OpsLaneEntry> {
        let lane = this.lanes.get(batchId)
        if (!lane) {
            lane = new Map()
            this.lanes.set(batchId, lane)
        }
        return lane
    }

    private resolutionMemo(batchId: number): Map<string, string | null> {
        let memo = this.resolutions.get(batchId)
        if (!memo) {
            memo = new Map()
            this.resolutions.set(batchId, memo)
        }
        return memo
    }

    private personStateMemo(batchId: number): Map<string, InternalPerson> {
        let memo = this.personState.get(batchId)
        if (!memo) {
            memo = new Map()
            this.personState.set(batchId, memo)
        }
        return memo
    }
}
