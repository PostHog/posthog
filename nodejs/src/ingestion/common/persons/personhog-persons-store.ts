import { DateTime } from 'luxon'
import pLimit from 'p-limit'
import { Counter } from 'prom-client'

import { PersonHogPersonWriteRepository } from '~/common/personhog/personhog-person-write-repository'
import { PersonhogPropertiesSizeError } from '~/common/personhog/persons'
import { PersonMessage } from '~/common/persons/person-message'
import { InternalPersonWithDistinctId } from '~/common/persons/repositories/person-repository'
import { PersonRepositoryTransaction } from '~/common/persons/repositories/person-repository-transaction'
import { CreatePersonResult, MoveDistinctIdsResult } from '~/common/utils/db/db'
import { generateKafkaPersonUpdateMessage } from '~/common/utils/db/utils'
import { logger } from '~/common/utils/logger'
import { NoRowsUpdatedError } from '~/common/utils/utils'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, PropertiesLastOperation, PropertiesLastUpdatedAt, Team } from '~/types'

import { EventOps, applyEventPropertyUpdates, computeOpsScalarUpdates, foldOps, refineEventOps } from './person-update'
import { FlushResult } from './persons-store'
import { PersonsStoreForBatch, PersonsStoreTransactionForBatch } from './persons-store-for-batch'

export const personhogStoreFlushCounter = new Counter({
    name: 'personhog_store_flush_ops_total',
    help: 'Folded person updates flushed to the personhog leader, by outcome',
    labelNames: ['outcome'],
})

export interface PersonhogPersonsStoreOptions {
    /** Concurrent leader calls during flush. */
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
 * A store verb whose leader support does not exist yet. Reaching one is a
 * wiring error — merge execution must stay gated off the personhog world
 * until the leader grows these — so it fails loudly instead of no-oping
 * into silent divergence.
 */
export class PersonhogPendingRpcError extends Error {
    constructor(method: string, needs: string) {
        super(`PersonhogPersonsStore.${method} requires leader support that does not exist yet: ${needs}`)
        this.name = 'PersonhogPendingRpcError'
    }
}

interface OpsLaneEntry {
    teamId: number
    personId: string
    distinctId: string
    /**
     * The person's version when the lane opened. Flush publishes the
     * ClickHouse row when the final version cleared this floor even if
     * the last response reported no change — a retried call whose first
     * attempt landed but whose response was lost replays into the
     * leader's no-change fast path, and the version is what still tells
     * the truth.
     */
    baseVersion: number
    /**
     * Folded ops in arrival order. Almost always one segment; a new one
     * starts only when foldOps reports a composition the ops vocabulary
     * cannot represent, and flush ships segments sequentially so the
     * leader refines between them — restoring sequential semantics for
     * exactly the case folding would corrupt.
     */
    segments: EventOps[]
}

/**
 * The personhog implementation of the person store: distinct-id
 * resolution and person creation through the identity service's
 * get-or-create, person state through the leader's strong reads, and
 * property updates as raw op folds shipped to the leader, which refines
 * them against authoritative state under the per-person lock.
 *
 * Where the Postgres store refines ops against a fetched snapshot before
 * writing, this store ships them as stated — the leader is this world's
 * refinement engine, so no version-race machinery exists here at all.
 * Fetches memoize per batch; folded ops accumulate per (batch, person)
 * and flush as one call per person.
 *
 * Person uuids are derived deterministically from team_id:distinct_id by
 * the identity service — the uuid argument to createPerson is advisory
 * and the returned person carries the authoritative one.
 */
export class PersonhogPersonsStore {
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
     * fold for a person this holds the pending projection — the batch's
     * read-your-write view, exactly as the Postgres store's cache holds
     * its accumulating PersonUpdate — and fetches must not clobber it
     * with service state.
     */
    private personState: Map<number, Map<string, InternalPerson>> = new Map()

    constructor(
        private repository: PersonHogPersonWriteRepository,
        options?: Partial<PersonhogPersonsStoreOptions>
    ) {
        this.options = { ...DEFAULT_OPTIONS, ...options }
    }

    forBatch(batchId: number): PersonsStoreForBatch {
        return new BatchBoundPersonhogStore(this, batchId)
    }

    async fetchForChecking(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const cached = this.lookupMemo(teamId, distinctId, batchId)
        if (cached !== undefined) {
            return cached
        }
        const results = await this.repository.fetchPersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        return this.recordFetch(teamId, distinctId, results[0] ?? null, batchId)
    }

    async fetchForUpdate(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const cached = this.lookupMemo(teamId, distinctId, batchId)
        if (cached !== undefined) {
            return cached
        }
        const results = await this.repository.fetchPersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG, {
            consistency: 'strong',
        })
        return this.recordFetch(teamId, distinctId, results[0] ?? null, batchId)
    }

    async fetchPersonsForUpdateByDistinctIds(
        teamId: number,
        distinctIds: string[],
        batchId: number
    ): Promise<InternalPersonWithDistinctId[]> {
        const results = await this.repository.fetchPersonsByDistinctIds(
            distinctIds.map((distinctId) => ({ teamId, distinctId })),
            CALLER_TAG,
            { consistency: 'strong' }
        )
        // Pending projections win over fetched state here too, so the
        // merge planner reads the same pre-flush view the update path
        // does.
        return results.map((person) => {
            const recorded = this.recordFetch(teamId, person.distinct_id, person, batchId)
            return { ...(recorded as InternalPerson), distinct_id: person.distinct_id } as InternalPersonWithDistinctId
        })
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
            resolutions.set(`${teamId}:${distinctId}`, null)
            return null
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

        const lane = this.opsLane(batchId)
        const personKey = `${person.team_id}:${person.id}`
        const existing = lane.get(personKey)
        if (!existing) {
            lane.set(personKey, {
                teamId: person.team_id,
                personId: person.id,
                distinctId,
                baseVersion: person.version,
                segments: [ops],
            })
        } else {
            const last = existing.segments.length - 1
            const folded = foldOps(existing.segments[last], ops)
            if (folded === null) {
                existing.segments.push(ops)
            } else {
                existing.segments[last] = folded
            }
        }

        // A local projection for the caller: the same application the
        // Postgres world would perform, so the processor returns a
        // sensible person. The leader's application at flush remains the
        // authoritative one for this world.
        const refined = refineEventOps(ops, person.properties ?? {}, this.options.updateAllProperties, false)
        const [projected] = applyEventPropertyUpdates(refined, person)
        Object.assign(projected, computeOpsScalarUpdates(ops, projected))
        // Person state now holds the pending projection, exactly as the
        // Postgres store's cache holds its accumulating PersonUpdate:
        // every distinct id resolving to this person sees the change
        // pre-flush, and the next event's projection composes on top.
        // Merges depend on this — merged properties are computed from
        // the projection, so pending ops travel to the merge target
        // through it.
        this.personStateMemo(batchId).set(personKey, projected)
        this.resolutionMemo(batchId).set(`${person.team_id}:${distinctId}`, personKey)
        return Promise.resolve([projected, []])
    }

    /**
     * Deletion pends leader-mediated support: the service's DeletePersons
     * RPC routes to the replica — a direct Postgres write the leader's
     * cache and changelog never observe, which is exactly the
     * resurrection hazard this world exists to close.
     */
    deletePersons(persons: InternalPerson[], _distinctId: string): Promise<PersonMessage[]> {
        if (persons.length === 0) {
            return Promise.resolve([])
        }
        throw new PersonhogPendingRpcError('deletePersons', 'a leader-mediated delete')
    }

    deletePerson(person: InternalPerson, distinctId: string): Promise<PersonMessage[]> {
        return this.deletePersons([person], distinctId)
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
        _forceUpdate?: boolean
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        const unsupported = Object.keys(otherUpdates).filter((key) => key !== 'is_identified' && key !== 'last_seen_at')
        if (unsupported.length > 0) {
            throw new PersonhogPendingRpcError(
                'updatePersonWithPropertiesDiffForUpdate',
                `UpdatePersonProperties fields for ${unsupported.join(', ')}`
            )
        }
        const { person: updated, updated: didUpdate } = await this.repository.updatePersonProperties(
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
        return [updated, didUpdate ? [generateKafkaPersonUpdateMessage(updated)] : [], false]
    }

    /**
     * Counts by fetching: the RPC surface has no dedicated count, and the
     * merge pre-check consuming this runs at shadow-team scale, where
     * fetching the ids to count them is acceptable. Absent persons count
     * zero, matching the SQL count.
     */
    async countDistinctIdsForPersons(
        teamId: Team['id'],
        personIds: InternalPerson['id'][]
    ): Promise<Map<string, number>> {
        const byPerson = await this.repository.getDistinctIdsForPersons(teamId, personIds, undefined, CALLER_TAG)
        return new Map(personIds.map((id) => [id, byPerson[id]?.length ?? 0]))
    }

    async fetchPersonDistinctIds(person: InternalPerson, limit?: number): Promise<string[]> {
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

    prefetchPersons(_teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void> {
        // A warming hint only; resolution memoizes on first touch instead.
        return Promise.resolve()
    }

    /**
     * Ships the batch's folded lanes to the leader, one entry per
     * person, segments in order. There is deliberately no Postgres
     * fallback: this store's world is the leader's. A missing person
     * (deleted or merged mid-batch) and the leader's size rejection are
     * counted and skipped — neither can succeed on retry — but whatever
     * earlier segments already applied still publishes. Publication is
     * gated on the version floor rather than the last response's
     * no-change flag: a retried call whose lost first attempt landed
     * replays into the leader's no-change fast path, and the version is
     * what still tells the truth. Any other failure fails the flush so
     * the batch retries whole. Batch-scoped, so one batch's failure can
     * never discard a sibling batch's shipped results.
     *
     * Known parity gap, leader-side: the wire carries no force flag and
     * the leader's refinement omits the filtered-property rules, so the
     * no-op classification the Postgres world applies to filtered-only
     * changes does not exist in this world yet. Closing it is leader
     * work (a force field on the RPC plus the filter port), tracked
     * with the merge-enablement items.
     */
    async flush(batchId: number): Promise<FlushResult[]> {
        const lane = this.lanes.get(batchId)
        if (!lane) {
            return []
        }
        this.lanes.delete(batchId)
        const limit = pLimit(this.options.maxConcurrentUpdates)
        const entries = [...lane.values()]

        const results = await Promise.all(
            entries.map((entry) =>
                limit(async (): Promise<FlushResult[]> => {
                    let finalPerson: InternalPerson | null = null
                    try {
                        for (const ops of entry.segments) {
                            const { person } = await this.repository.updatePersonProperties(
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
                            finalPerson = person ?? finalPerson
                        }
                        personhogStoreFlushCounter.inc({ outcome: 'success' })
                    } catch (error) {
                        if (error instanceof NoRowsUpdatedError) {
                            // The person was merged or deleted since the
                            // fold. In-batch that is fine — the merge
                            // carried the pending projection to its
                            // target. Cross-batch it drops the ops where
                            // the Postgres store re-resolves and
                            // re-applies; that re-resolution joins the
                            // merge-enablement work, and until merges
                            // are gated on, this counter firing means a
                            // bug, not a race.
                            personhogStoreFlushCounter.inc({ outcome: 'not_found' })
                        } else if (error instanceof PersonhogPropertiesSizeError) {
                            // Counted but not yet surfaced as the
                            // person_properties_size_violation ingestion
                            // warning the Postgres store emits — the
                            // store holds no outputs handle; warning
                            // parity lands with the shadow wiring.
                            personhogStoreFlushCounter.inc({ outcome: 'size_violation' })
                        } else {
                            personhogStoreFlushCounter.inc({ outcome: 'error' })
                            logger.error('Failed to flush folded update to personhog', {
                                teamId: entry.teamId,
                                personId: entry.personId,
                                error,
                            })
                            throw error
                        }
                    }
                    if (!finalPerson || finalPerson.version <= entry.baseVersion) {
                        return []
                    }
                    return [
                        {
                            messages: [generateKafkaPersonUpdateMessage(finalPerson)],
                            teamId: entry.teamId,
                            distinctId: entry.distinctId,
                            uuid: finalPerson.uuid,
                        },
                    ]
                })
            )
        )
        return results.flat()
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

/**
 * The batch-bound view: batchId curried. It doubles as its own
 * transaction view — `inTransaction` is a passthrough, because this
 * world has no client-side transactions. Merge safety comes from the
 * merge flow's own progress tracking over idempotent leader verbs, and
 * the merge-execution verbs themselves throw until the leader grows
 * them, so the passthrough cannot silently half-merge today.
 */
class BatchBoundPersonhogStore implements PersonsStoreForBatch, PersonsStoreTransactionForBatch {
    constructor(
        private readonly store: PersonhogPersonsStore,
        public readonly batchId: number
    ) {}

    fetchForChecking(teamId: number, distinctId: string): Promise<InternalPerson | null> {
        return this.store.fetchForChecking(teamId, distinctId, this.batchId)
    }

    fetchForUpdate(teamId: number, distinctId: string): Promise<InternalPerson | null> {
        return this.store.fetchForUpdate(teamId, distinctId, this.batchId)
    }

    fetchPersonsForUpdateByDistinctIds(teamId: number, distinctIds: string[]): Promise<InternalPersonWithDistinctId[]> {
        return this.store.fetchPersonsForUpdateByDistinctIds(teamId, distinctIds, this.batchId)
    }

    applyEventOps(
        person: InternalPerson,
        ops: EventOps,
        distinctId: string
    ): Promise<[InternalPerson, PersonMessage[]]> {
        return this.store.applyEventOps(person, ops, distinctId, this.batchId)
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
        extraDistinctIds?: { distinctId: string; version?: number }[]
    ): Promise<CreatePersonResult> {
        return this.store.createPerson(
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
            this.batchId
        )
    }

    deletePersons(persons: InternalPerson[], distinctId: string): Promise<PersonMessage[]> {
        return this.store.deletePersons(persons, distinctId)
    }

    deletePerson(
        person: InternalPerson,
        distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<PersonMessage[]> {
        return this.store.deletePerson(person, distinctId)
    }

    inTransaction<T>(
        _description: string,
        transaction: (tx: PersonsStoreTransactionForBatch) => Promise<T>
    ): Promise<T> {
        return transaction(this)
    }

    updatePersonWithPropertiesDiffForUpdate(
        person: InternalPerson,
        propertiesToSet: Properties,
        propertiesToUnset: string[],
        otherUpdates: Partial<InternalPerson>,
        distinctId: string,
        forceUpdate?: boolean,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        return this.store.updatePersonWithPropertiesDiffForUpdate(
            person,
            propertiesToSet,
            propertiesToUnset,
            otherUpdates,
            distinctId,
            forceUpdate
        )
    }

    countDistinctIdsForPersons(
        teamId: Team['id'],
        personIds: InternalPerson['id'][],
        _distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<Map<string, number>> {
        return this.store.countDistinctIdsForPersons(teamId, personIds)
    }

    fetchPersonDistinctIds(
        person: InternalPerson,
        _distinctId: string,
        limit?: number,
        _tx?: PersonRepositoryTransaction
    ): Promise<string[]> {
        return this.store.fetchPersonDistinctIds(person, limit)
    }

    // Merge execution pends leader support; each verb names what it waits
    // on. Shadow processing must gate merge events off this world until
    // these land.
    //
    // Contract for the eventual implementations: clear the source
    // persons' fold lanes as the last step. The lanes' pending content
    // already traveled to the merge target through the memo projection
    // that merged-property computation reads, so a same-batch merge or
    // delete must not flush a guaranteed-NotFound update — the flush's
    // not_found outcome exists to signal cross-batch races, and routine
    // merges would drown that signal.

    updatePersonForMerge(
        _person: InternalPerson,
        _update: Partial<InternalPerson>,
        _distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<[InternalPerson, PersonMessage[], boolean]> {
        throw new PersonhogPendingRpcError(
            'updatePersonForMerge',
            'created_at min-merge and merge version semantics on UpdatePersonProperties'
        )
    }

    addDistinctId(_person: InternalPerson, _distinctId: string, _version: number): Promise<PersonMessage[]> {
        throw new PersonhogPendingRpcError('addDistinctId', 'an idempotent AddDistinctId RPC')
    }

    moveDistinctIds(
        _source: InternalPerson,
        _target: InternalPerson,
        _distinctId: string,
        _limit?: number,
        _tx?: PersonRepositoryTransaction
    ): Promise<MoveDistinctIdsResult> {
        throw new PersonhogPendingRpcError('moveDistinctIds', 'an idempotent MoveDistinctIds RPC')
    }

    moveDistinctIdsFromPersons(
        _sources: InternalPerson[],
        _target: InternalPerson,
        _distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<MoveDistinctIdsResult> {
        throw new PersonhogPendingRpcError('moveDistinctIdsFromPersons', 'an idempotent MoveDistinctIds RPC')
    }

    // Postgres bookkeeping with nothing to answer in this world: shadow
    // teams are fresh, so no cohort rows or hash-key overrides exist to
    // fix up, and the personless surface is being deleted outright.

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

    /** The leader enforces the properties-size ceiling at admission. */
    personPropertiesSize(_personId: string, _teamId: number): Promise<number> {
        return Promise.resolve(0)
    }

    // The personless writers cannot no-op: their caller marks the
    // process-global personless LRU as inserted after each call, and
    // that cache is shared with the Postgres path — a silent no-op here
    // records rows that were never written, permanently skipping the
    // real insert if the Postgres world ever serves the team. Personless
    // is slated for deletion; until then the shadow must gate these
    // events off this world, and reaching one is a wiring bug.

    addPersonlessDistinctId(_teamId: number, _distinctId: string): Promise<boolean> {
        throw new PersonhogPendingRpcError('addPersonlessDistinctId', 'personless support (slated for deletion)')
    }

    addPersonlessDistinctIdForMerge(
        _teamId: number,
        _distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<boolean> {
        throw new PersonhogPendingRpcError(
            'addPersonlessDistinctIdForMerge',
            'personless support (slated for deletion)'
        )
    }

    processPersonlessDistinctIdsBatch(_entries: { teamId: number; distinctId: string }[]): Promise<void> {
        throw new PersonhogPendingRpcError(
            'processPersonlessDistinctIdsBatch',
            'personless support (slated for deletion)'
        )
    }

    /** A read with a "no batch result" answer; safe to leave callers falling back. */
    getPersonlessBatchResult(_teamId: number, _distinctId: string): boolean | undefined {
        return undefined
    }

    removeDistinctIdFromCache(teamId: number, distinctId: string): void {
        this.store.removeDistinctIdFromCache(teamId, distinctId)
    }

    prefetchPersons(teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void> {
        return this.store.prefetchPersons(teamDistinctIds)
    }

    flush(): Promise<FlushResult[]> {
        return this.store.flush(this.batchId)
    }

    shutdown(): Promise<void> {
        return this.store.shutdown()
    }
}
