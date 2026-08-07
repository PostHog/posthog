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

import { EventOps, applyEventPropertyUpdates, foldOps, refineEventOps } from './person-update'
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
}

const DEFAULT_OPTIONS: PersonhogPersonsStoreOptions = {
    maxConcurrentUpdates: 10,
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
    ops: EventOps
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
    /** Resolution memo per batch, keyed by `${teamId}:${distinctId}`. */
    private resolved: Map<number, Map<string, InternalPerson | null>> = new Map()

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
        const memo = this.resolutionMemo(batchId)
        const key = `${teamId}:${distinctId}`
        const cached = memo.get(key)
        if (cached !== undefined) {
            return cached
        }
        const results = await this.repository.fetchPersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG)
        return results[0] ?? null
    }

    async fetchForUpdate(teamId: number, distinctId: string, batchId: number): Promise<InternalPerson | null> {
        const memo = this.resolutionMemo(batchId)
        const key = `${teamId}:${distinctId}`
        const cached = memo.get(key)
        if (cached !== undefined) {
            return cached
        }
        const results = await this.repository.fetchPersonsByDistinctIds([{ teamId, distinctId }], CALLER_TAG, {
            consistency: 'strong',
        })
        const person = results[0] ?? null
        memo.set(key, person)
        return person
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
        const memo = this.resolutionMemo(batchId)
        for (const person of results) {
            memo.set(`${teamId}:${person.distinct_id}`, person)
        }
        return results
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
        const memo = this.resolutionMemo(batchId)
        memo.set(`${teamId}:${primaryDistinctId.distinctId}`, person)
        for (const extra of extraDistinctIds ?? []) {
            memo.set(`${teamId}:${extra.distinctId}`, person)
        }
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
        if (ops.denied) {
            return Promise.resolve([person, []])
        }

        const lane = this.opsLane(batchId)
        const key = `${person.team_id}:${person.id}`
        const existing = lane.get(key)
        lane.set(key, {
            teamId: person.team_id,
            personId: person.id,
            distinctId,
            ops: existing ? foldOps(existing.ops, ops) : ops,
        })

        // A local projection for the caller: the same application the
        // Postgres world would perform, so the processor returns a
        // sensible person. The leader's application at flush remains the
        // authoritative one for this world.
        const refined = refineEventOps(ops, person.properties ?? {}, true)
        const [projected] = applyEventPropertyUpdates(refined, person)
        if (ops.isIdentified) {
            projected.is_identified = true
        }
        if (ops.lastSeenAtMs !== undefined) {
            const candidate = DateTime.fromMillis(ops.lastSeenAtMs, { zone: 'utc' })
            if (!projected.last_seen_at || candidate > projected.last_seen_at) {
                projected.last_seen_at = candidate
            }
        }
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
        const key = `${teamId}:${distinctId}`
        for (const memo of this.resolved.values()) {
            memo.delete(key)
        }
    }

    prefetchPersons(_teamDistinctIds: { teamId: number; distinctId: string; batchId: number }[]): Promise<void> {
        // A warming hint only; resolution memoizes on first touch instead.
        return Promise.resolve()
    }

    /**
     * Ships every folded lane to the leader, one call per person. There
     * is deliberately no Postgres fallback: this store's world is the
     * leader's. A missing person (deleted or merged mid-batch) and the
     * leader's size rejection are counted and skipped — neither can
     * succeed on retry — while any other failure fails the flush so the
     * batch retries whole.
     */
    async flush(): Promise<FlushResult[]> {
        const limit = pLimit(this.options.maxConcurrentUpdates)
        const entries = [...this.lanes.values()].flatMap((lane) => [...lane.values()])
        this.lanes.clear()

        const results = await Promise.all(
            entries.map((entry) =>
                limit(async (): Promise<FlushResult[]> => {
                    try {
                        const { person, updated } = await this.repository.updatePersonProperties(
                            {
                                teamId: entry.teamId,
                                personId: entry.personId,
                                eventName: entry.ops.eventName,
                                setProperties: entry.ops.set,
                                setOnceProperties: entry.ops.setOnce,
                                unsetProperties: entry.ops.unset,
                                isIdentified: entry.ops.isIdentified,
                                lastSeenAtMs: entry.ops.lastSeenAtMs,
                            },
                            CALLER_TAG
                        )
                        personhogStoreFlushCounter.inc({ outcome: 'success' })
                        if (!updated || !person) {
                            return []
                        }
                        return [
                            {
                                messages: [generateKafkaPersonUpdateMessage(person)],
                                teamId: entry.teamId,
                                distinctId: entry.distinctId,
                                uuid: person.uuid,
                            },
                        ]
                    } catch (error) {
                        if (error instanceof NoRowsUpdatedError) {
                            personhogStoreFlushCounter.inc({ outcome: 'not_found' })
                            return []
                        }
                        if (error instanceof PersonhogPropertiesSizeError) {
                            personhogStoreFlushCounter.inc({ outcome: 'size_violation' })
                            return []
                        }
                        personhogStoreFlushCounter.inc({ outcome: 'error' })
                        logger.error('Failed to flush folded update to personhog', {
                            teamId: entry.teamId,
                            personId: entry.personId,
                            error,
                        })
                        throw error
                    }
                })
            )
        )
        return results.flat()
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

    private resolutionMemo(batchId: number): Map<string, InternalPerson | null> {
        let memo = this.resolved.get(batchId)
        if (!memo) {
            memo = new Map()
            this.resolved.set(batchId, memo)
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

    addPersonlessDistinctId(_teamId: number, _distinctId: string): Promise<boolean> {
        return Promise.resolve(false)
    }

    addPersonlessDistinctIdForMerge(
        _teamId: number,
        _distinctId: string,
        _tx?: PersonRepositoryTransaction
    ): Promise<boolean> {
        return Promise.resolve(false)
    }

    processPersonlessDistinctIdsBatch(_entries: { teamId: number; distinctId: string }[]): Promise<void> {
        return Promise.resolve()
    }

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
        return this.store.flush()
    }

    shutdown(): Promise<void> {
        return this.store.shutdown()
    }
}
