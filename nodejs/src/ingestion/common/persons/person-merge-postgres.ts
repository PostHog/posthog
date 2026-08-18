import { DateTime } from 'luxon'
import { Counter, Histogram } from 'prom-client'

import { PERSON_MERGE_EVENTS_OUTPUT } from '~/common/outputs'
import { personMergeFailureCounter } from '~/common/persons/metrics'
import { PersonMessage } from '~/common/persons/person-message'
import { isDistinctIdIllegal } from '~/common/persons/person-utils'
import {
    PersonClaimedByLifecycleOpError,
    PersonTombstoneBlockedError,
} from '~/common/persons/repositories/person-repository'
import { logger } from '~/common/utils/logger'
import { promiseRetry } from '~/common/utils/retries'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson, ValueMatcher } from '~/types'

import type { BatchWritingPersonsStore } from './batch-writing-person-store'
import { PersonOutputs } from './person-context'
import { PersonCreateService } from './person-create-service'
import { buildPersonMergeEventMessage } from './person-merge-event'
import {
    PersonMergeLimitExceededError,
    PersonMergeRaceConditionError,
    PersonMergeResult,
    SourcePersonHasDistinctIdsError,
    SourcePersonNotFoundError,
    TargetPersonNotFoundError,
    mergeError,
    mergeSuccess,
} from './person-merge-types'
import { applyEventPropertyUpdates, refineEventOps } from './person-update'
import { lifecycleOpIdFromEvent } from './person-uuid'
import {
    MergeFoldAbortReason,
    MergePersonsRequest,
    MergePersonsResult,
    MergePersonsSource,
    MergePersonsSourceResult,
} from './persons-store'
import {
    BatchBoundPersonsStore,
    BatchBoundPersonsStoreTransaction,
    PersonsStoreForBatch,
    PersonsStoreTransactionForBatch,
} from './persons-store-for-batch'

export const mergeTxnAttemptCounter = new Counter({
    name: 'person_merge_txn_attempt_total',
    help: 'Number of person merge attempts.',
    labelNames: ['call', 'oldPersonIdentified', 'newPersonIdentified'],
})

export const mergeTxnSuccessCounter = new Counter({
    name: 'person_merge_txn_success_total',
    help: 'Number of person merges that succeeded.',
    labelNames: ['call', 'oldPersonIdentified', 'newPersonIdentified'],
})

export const mergeFoldExecutedCounter = new Counter({
    name: 'person_merge_fold_executed_total',
    help: 'Number of folded merge transactions executed.',
})

export const mergeFoldSizeHistogram = new Histogram({
    name: 'person_merge_fold_size',
    help: 'Number of merge pairs folded into one transaction.',
    buckets: [2, 5, 10, 25, 50, 100, 250, 500],
})

export const mergeDistinctIdOverrideCounter = new Counter({
    name: 'person_merge_distinct_id_override_total',
    help: 'Distinct id mapping rows written during merges, each writing a ClickHouse override row.',
    labelNames: ['call'],
})

export const personMergeEventProducedCounter = new Counter({
    name: 'person_merge_event_produced_total',
    help: 'Number of person_merge_events messages acked by the broker (gate-on merges only).',
})

/** Thrown inside the fold transaction to roll it back when merge-mode move bounds would be exceeded. */
class MergeFoldLimitError extends Error {}

/** Thrown inside the fold transaction to roll it back when a concurrent merge invalidated the fetched sources. */
class MergeFoldConflictError extends Error {}

/** Maps a fold failure to the abort reason the caller's fallback counter records. */
function foldAbortReason(error: unknown): MergeFoldAbortReason {
    if (error instanceof MergeFoldLimitError) {
        return 'limit'
    }
    if (
        error instanceof MergeFoldConflictError ||
        error instanceof PersonTombstoneBlockedError ||
        error instanceof PersonClaimedByLifecycleOpError
    ) {
        return 'conflict'
    }
    if ((error as { code?: string })?.code === '40P01') {
        return 'deadlock'
    }
    return 'error'
}

/** One ack the caller can await for a set of produces already in flight. */
async function joinAcks(...acks: Promise<void>[]): Promise<void> {
    await Promise.all(acks)
}

/** Gate + partition-count + team allowlist for the cross-partition merge-event producer. */
export interface MergeEventsConfig {
    enabled: boolean
    partitionCount: number
    /** Matches teams allowed to emit merge events; the pg store builds it from PERSON_MERGE_EVENTS_TEAM_ALLOWLIST. */
    isTeamEnabled: ValueMatcher<number>
}

/** The Postgres backend's merge policy, derived from config at store construction. */
export interface PostgresMergePolicy {
    /** When true, all property changes trigger person updates; mirrors the store option of the same name. */
    updateAllProperties: boolean
    /** Teams on the new-world merge behavior: lifecycle-mark claims plus tombstone deletes. */
    isTombstoneTeam: ValueMatcher<number>
    mergeEvents: MergeEventsConfig
}

/**
 * The Postgres implementation of PersonsStore.mergePersons:
 * classification, lifecycle-mark claims, distinct-id moves, cohort
 * fixups, and source deletion, run against the pg store's own verbs
 * and transactions. One instance serves one request. Settled verdicts
 * come back as per-source outcomes; retryable conflicts (lifecycle
 * claims, tombstone races, creation races) throw for the caller's
 * retry loop, which re-enters with fresh fetches.
 */
export class PostgresPersonMerge {
    private batchStore: PersonsStoreForBatch
    private createService: PersonCreateService

    constructor(
        private store: BatchWritingPersonsStore,
        private outputs: PersonOutputs,
        private policy: PostgresMergePolicy,
        private request: MergePersonsRequest,
        private batchId: number
    ) {
        this.batchStore = new BatchBoundPersonsStore(store, batchId)
        this.createService = new PersonCreateService(this.batchStore, outputs)
    }

    private get teamId(): number {
        return this.request.teamId
    }

    /** The processing distinct id stamped on verb calls; merges always process under the target's id. */
    private get targetDistinctId(): string {
        return this.request.targetDistinctId
    }

    private get eventName(): string {
        return this.request.eventOps.eventName
    }

    private get timestamp(): DateTime {
        return DateTime.fromMillis(this.request.createdAtMs, { zone: 'utc' })
    }

    private tombstoneEnabled(): boolean {
        return this.policy.isTombstoneTeam(this.teamId)
    }

    async execute(): Promise<MergePersonsResult> {
        if (this.request.sources.length === 0) {
            throw new Error('mergePersons requires at least one source')
        }
        if (this.request.sources.length > 1) {
            return await this.executeFold()
        }
        return await this.mergeSingleWithCachePurge(this.request.sources[0])
    }

    /**
     * Runs a single-source merge, purging both ids from the batch caches
     * on any throw: merge verbs update the caches optimistically inside a
     * transaction that has now rolled back, and a retry must re-read
     * committed state rather than a mapping that was never committed.
     */
    private async mergeSingleWithCachePurge(source: MergePersonsSource): Promise<MergePersonsResult> {
        try {
            return await this.mergeSingle(source)
        } catch (error) {
            this.store.removeDistinctIdFromCache(this.teamId, this.targetDistinctId)
            this.store.removeDistinctIdFromCache(this.teamId, source.distinctId)
            throw error
        }
    }

    private inTransaction<T>(
        description: string,
        body: (tx: PersonsStoreTransactionForBatch) => Promise<T>
    ): Promise<T> {
        return this.store.inTransaction(description, (tx) =>
            body(new BatchBoundPersonsStoreTransaction(tx, this.batchId))
        )
    }

    private async produceMessages(messages: PersonMessage[]): Promise<void> {
        await Promise.all(
            messages.map((msg) =>
                this.outputs.produce(msg.output, { value: msg.value, key: null, teamId: this.teamId })
            )
        )
    }

    /**
     * Best-effort emit of a person_merge_events message for the cohort-stream-processor. No-op when
     * the gate is off or the team is outside the allowlist. Never throws: a produce failure is
     * logged and dropped, so it can never affect ingestion. Delivery is at-most-once; loss is
     * accepted until the delivery-guarantees milestone. The message is explicitly partitioned by
     * `(team_id, P_old)` so it reaches the worker holding P_old's state — see `buildPersonMergeEventMessage`.
     */
    private async producePersonMergeEvent(sourcePerson: InternalPerson, targetPerson: InternalPerson): Promise<void> {
        if (!this.policy.mergeEvents.enabled || !this.policy.mergeEvents.isTeamEnabled(this.teamId)) {
            return
        }
        try {
            const { key, partition, value } = buildPersonMergeEventMessage(
                this.teamId,
                sourcePerson.uuid,
                targetPerson.uuid,
                Date.now(),
                this.policy.mergeEvents.partitionCount
            )
            await this.outputs.produce(PERSON_MERGE_EVENTS_OUTPUT, {
                value,
                key,
                partition,
                teamId: this.teamId,
            })
            personMergeEventProducedCounter.inc()
        } catch (error) {
            logger.warn('person_merge_events produce failed, dropping', {
                team_id: this.teamId,
                source_person_uuid: sourcePerson.uuid,
                target_person_uuid: targetPerson.uuid,
                error,
            })
        }
    }

    private async mergeSingle(source: MergePersonsSource): Promise<MergePersonsResult> {
        const otherPersonDistinctId = source.distinctId
        const mergeIntoDistinctId = this.targetDistinctId
        const teamId = this.teamId

        const otherPerson = await this.store.fetchForUpdate(teamId, otherPersonDistinctId, this.batchId)
        const mergeIntoPerson = await this.store.fetchForUpdate(teamId, mergeIntoDistinctId, this.batchId)

        // A note about the `distinctIdVersion` logic you'll find below:
        //
        // Overrides are only created for `posthog_persondistinctid` rows with version > 0, see:
        //   https://github.com/PostHog/posthog/blob/92e17ce307a577c4233d4ab252eebc6c2207a5ee/posthog/models/person/sql.py#L269-L287
        //
        // With $process_person_profile=false, events can exist in ClickHouse stamped with the
        // deterministic implied person uuid even though no `posthog_persondistinctid` or
        // `posthog_person` rows exist. So every merge-added mapping for a distinct id without a
        // person gets version 1: the override either re-points real personless events or is a
        // harmless transient row the squash job deletes within days. The exception is the distinct
        // id whose uuid a newly created person is born on — its events already point at the right
        // person, so it keeps version 0 and stays out of the overrides join.

        if ((otherPerson && !mergeIntoPerson) || (!otherPerson && mergeIntoPerson)) {
            // Only one of the two Distinct IDs points at an existing Person

            const [existingPerson, distinctIdToAdd] = (() => {
                if (otherPerson) {
                    return [otherPerson!, mergeIntoDistinctId]
                } else {
                    return [mergeIntoPerson!, otherPersonDistinctId]
                }
            })()

            this.discardOverrideCounts()
            const lifecycleOpId = lifecycleOpIdFromEvent(teamId, this.request.opId)
            const result = await this.inTransaction('mergeDistinctIds-OneExists', async (tx) => {
                // New-world merges claim the person's lifecycle mark, which keeps a concurrent
                // tombstone from landing between this check and the distinct id insert (an
                // orphaned mapping); old-world merges rely on the delete's FK violation instead.
                if (this.tombstoneEnabled()) {
                    await tx.claimLifecycleMarks(
                        lifecycleOpId,
                        existingPerson.team_id,
                        [{ personId: existingPerson.id, personUuid: existingPerson.uuid, role: 'target' }],
                        this.targetDistinctId
                    )
                    if (!(await tx.isPersonLive(existingPerson, this.targetDistinctId))) {
                        // Purge the stale cache entries so the caller's retry attempt
                        // re-fetches from Postgres instead of replaying the cached,
                        // now-tombstoned person into the same failure.
                        this.store.removeDistinctIdFromCache(teamId, otherPersonDistinctId)
                        this.store.removeDistinctIdFromCache(teamId, mergeIntoDistinctId)
                        throw new TargetPersonNotFoundError(
                            'Person was deleted before the merge could add a distinct id'
                        )
                    }
                }
                // See comment above about `distinctIdVersion`
                const distinctIdVersion = 1
                this.recordOverrideCount('oneExists')

                const kafkaMessages = await tx.addDistinctId(existingPerson, distinctIdToAdd, distinctIdVersion)
                await this.produceMessages(kafkaMessages)
                if (this.tombstoneEnabled()) {
                    await tx.releaseLifecycleMarks(lifecycleOpId, teamId, this.targetDistinctId)
                }
                return existingPerson
            })
            this.flushOverrideCounts()
            return {
                survivor: result,
                results: [{ sourceDistinctId: otherPersonDistinctId, outcome: 'attached' }],
            }
        } else if (otherPerson && mergeIntoPerson) {
            // Both Distinct IDs point at an existing Person

            if (otherPerson.id == mergeIntoPerson.id) {
                // Nothing to do, they are the same Person
                return {
                    survivor: mergeIntoPerson,
                    results: [
                        {
                            sourceDistinctId: otherPersonDistinctId,
                            outcome: 'noop_same_person',
                            sourcePersonUuid: otherPerson.uuid,
                        },
                    ],
                }
            }

            return await this.mergePeople({
                mergeInto: mergeIntoPerson,
                mergeIntoDistinctId: mergeIntoDistinctId,
                otherPerson: otherPerson,
                otherPersonDistinctId: otherPersonDistinctId,
            })
        } else {
            // Neither Distinct ID points at an existing Person

            const distinctId1 = mergeIntoDistinctId
            const distinctId2 = otherPersonDistinctId

            this.discardOverrideCounts()
            const [person, needsPersonUpdate] = await this.inTransaction(
                'mergeDistinctIds-NeitherExist',
                async (tx) => {
                    // See comment above about `distinctIdVersion`: the first Distinct ID derives the
                    // new Person's UUID so it never needs an override; the second always gets one.
                    const distinctId1Version = 0
                    const distinctId2Version = 1
                    this.recordOverrideCount('neitherExist')

                    const [created, wasCreated] = await this.createService.createPerson(
                        this.timestamp,
                        this.request.eventOps.set,
                        this.request.eventOps.setOnce,
                        teamId,
                        null,
                        true,
                        this.request.opId,
                        { distinctId: distinctId1, version: distinctId1Version },
                        [{ distinctId: distinctId2, version: distinctId2Version }],
                        tx
                    )
                    // If person was not created (creation conflict) and is not identified,
                    // we need to update it later
                    return [created, !wasCreated && !created.is_identified] as const
                }
            )
            this.flushOverrideCounts()
            return {
                survivor: person,
                results: [{ sourceDistinctId: otherPersonDistinctId, outcome: 'attached' }],
                survivorNeedsUpdate: needsPersonUpdate,
            }
        }
    }

    /**
     * Folded-merge execution for a multi-source request: every source
     * merges into the target inside one transaction. Any failure rolls
     * the fold back untouched and answers foldAborted, so the caller can
     * fall back to per-event sequential merges.
     */
    private async executeFold(): Promise<MergePersonsResult> {
        try {
            return await this.executeFoldInner()
        } catch (error) {
            const reason = foldAbortReason(error)
            // The batch store's caches were updated optimistically inside the
            // rolled-back transaction (distinct id → target mappings); purge
            // them so the sequential fallback re-reads committed state.
            this.store.removeDistinctIdFromCache(this.teamId, this.targetDistinctId)
            for (const source of this.request.sources) {
                this.store.removeDistinctIdFromCache(this.teamId, source.distinctId)
            }
            logger.warn('🤔', 'folded merge failed, falling back to sequential merges', {
                team_id: this.teamId,
                distinct_id: this.targetDistinctId,
                pairs: this.request.sources.length,
                reason,
                error,
            })
            return { survivor: null, results: [], foldAborted: reason }
        }
    }

    /**
     * Counts each folded source's distinct ids inside the transaction and
     * aborts the fold (rolling it back) when:
     * - a source is missing entirely — it was merged away between the locked
     *   fetch (whose locks were released at statement end) and the transaction,
     *   so its already-computed property contribution would be stale;
     * - a source's count exceeds the LIMIT/ASYNC move limit — those events
     *   need their own per-event DLQ/redirect decision;
     * - the total exceeds batched SYNC's per-statement batch size.
     * Returns the expected total so the caller can verify the move touched
     * exactly that many rows. One cheap indexed GROUP BY that rarely trips.
     */
    private async assertFoldSourcesWithinMoveBounds(
        tx: PersonsStoreTransactionForBatch,
        mergeSources: InternalPerson[]
    ): Promise<number> {
        if (mergeSources.length === 0) {
            return 0
        }
        const mergeMode = this.request.mergeMode
        const limit = mergeMode.type === 'SYNC' ? undefined : mergeMode.limit
        const batchSize = mergeMode.type === 'SYNC' ? mergeMode.batchSize : undefined

        const counts = await tx.countDistinctIdsForPersons(
            this.teamId,
            mergeSources.map((source) => source.id),
            this.targetDistinctId
        )
        let total = 0
        for (const source of mergeSources) {
            const count = counts.get(source.id)
            if (count === undefined) {
                throw new MergeFoldConflictError('folded merge source lost its distinct ids concurrently')
            }
            if (limit !== undefined && count > limit) {
                throw new MergeFoldLimitError('folded merge source exceeds distinct id move limit')
            }
            total += count
        }
        if (batchSize !== undefined && total > batchSize) {
            throw new MergeFoldLimitError('folded merge move exceeds sync batch size')
        }
        return total
    }

    private async executeFoldInner(): Promise<MergePersonsResult> {
        const teamId = this.teamId
        const outcomes: MergePersonsSourceResult[] = []
        let bootstrapAck: Promise<void> | undefined

        let target = await this.store.fetchForUpdate(teamId, this.targetDistinctId, this.batchId)
        let sourcesToFold = this.request.sources

        if (!target) {
            // Cold start: no target person yet. Bootstrap it through the
            // sequential path for the triggering event's source (which creates
            // the person or attaches the distinct_id), then fold the remaining
            // sources in their request order.
            const bootstrapSource =
                this.request.sources.find((source) => source.distinctId === this.request.triggerSourceDistinctId) ??
                this.request.sources[0]
            const bootstrap = await promiseRetry(
                () => this.mergeSingleWithCachePurge(bootstrapSource),
                'merge_distinct_ids'
            )
            if (!bootstrap.survivor) {
                throw new Error('merge fold bootstrap did not produce a target person')
            }
            target = bootstrap.survivor
            outcomes.push(...bootstrap.results)
            bootstrapAck = bootstrap.kafkaAck
            sourcesToFold = this.request.sources.filter((source) => source !== bootstrapSource)
        }

        const sources = await this.store.fetchPersonsForUpdateByDistinctIds(
            teamId,
            sourcesToFold.map((source) => source.distinctId),
            this.batchId
        )
        const sourceByDistinctId = new Map(sources.map((source) => [source.distinct_id, source]))

        // Partition sources, preserving order for property-merge precedence.
        const mergeSources: InternalPerson[] = []
        const mergedSourceOutcomes: MergePersonsSourceResult[] = []
        const seenSourceIds = new Set<string>([target.id])
        const missingSources: MergePersonsSource[] = []
        for (const pair of sourcesToFold) {
            if (isDistinctIdIllegal(pair.distinctId)) {
                outcomes.push({ sourceDistinctId: pair.distinctId, outcome: 'skipped_illegal' })
                continue
            }
            const source = sourceByDistinctId.get(pair.distinctId)
            if (!source) {
                missingSources.push(pair)
                continue
            }
            if (seenSourceIds.has(source.id)) {
                outcomes.push({
                    sourceDistinctId: pair.distinctId,
                    outcome: 'noop_same_person',
                    sourcePersonUuid: source.uuid,
                })
                continue
            }
            if (source.is_identified && !this.request.allowIdentifiedSources) {
                outcomes.push({
                    sourceDistinctId: pair.distinctId,
                    outcome: 'skipped_already_identified',
                    sourcePersonUuid: source.uuid,
                })
                continue
            }
            seenSourceIds.add(source.id)
            mergeSources.push(source)
            mergedSourceOutcomes.push({
                sourceDistinctId: pair.distinctId,
                outcome: 'merged',
                sourcePersonUuid: source.uuid,
            })
        }

        if (mergeSources.length === 0 && missingSources.length === 0) {
            return { survivor: target, results: outcomes, kafkaAck: bootstrapAck }
        }

        // Sequential property precedence: each source merges its properties
        // under the accumulated target's (target wins, earlier sources win
        // over later ones). Event $set/$set_once apply on top, as in mergePeople.
        let mergedProperties: Properties = target.properties
        for (const source of mergeSources) {
            mergedProperties = { ...source.properties, ...mergedProperties }
        }
        const propertyUpdates = refineEventOps(this.request.eventOps, mergedProperties, this.policy.updateAllProperties)
        const [updatedTempPerson] = applyEventPropertyUpdates(propertyUpdates, {
            ...target,
            properties: mergedProperties,
        })

        const createdAt = DateTime.min(target.created_at, ...mergeSources.map((source) => source.created_at))
        const version = Math.max(target.version, ...mergeSources.map((source) => source.version)) + 1

        const currentTarget = target
        this.discardOverrideCounts()
        const lifecycleOpId = lifecycleOpIdFromEvent(teamId, this.request.opId)
        const [mergedPerson, kafkaMessages] = await this.inTransaction('mergePeopleFold', async (tx) => {
            // New-world folds claim every person, keeping concurrent lifecycle operations
            // (other merges, the delete saga) off the targets and sources until commit.
            if (this.tombstoneEnabled()) {
                await tx.claimLifecycleMarks(
                    lifecycleOpId,
                    currentTarget.team_id,
                    [
                        { personId: currentTarget.id, personUuid: currentTarget.uuid, role: 'target' },
                        ...mergeSources.map((source, index) => ({
                            personId: source.id,
                            personUuid: source.uuid,
                            role: 'source' as const,
                            ordinal: index,
                        })),
                    ],
                    this.targetDistinctId
                )
                if (!(await tx.isPersonLive(currentTarget, this.targetDistinctId))) {
                    throw new MergeFoldConflictError('Fold target was deleted concurrently')
                }
            }
            const expectedMoveCount = await this.assertFoldSourcesWithinMoveBounds(tx, mergeSources)

            let person = currentTarget
            let updateMessages: PersonMessage[] = []
            if (mergeSources.length > 0) {
                ;[person, updateMessages] = await tx.updatePersonForMerge(
                    currentTarget,
                    {
                        created_at: createdAt,
                        properties: updatedTempPerson.properties,
                        is_identified: true,
                        version,
                    },
                    this.targetDistinctId
                )
            }

            const moveResult = await tx.moveDistinctIdsFromPersons(mergeSources, currentTarget, this.targetDistinctId)
            if (!moveResult.success) {
                throw new TargetPersonNotFoundError('Target person no longer exists')
            }
            // A mismatch means a concurrent merge touched the sources
            // between the count and the move; abort so the sequential path
            // (whose zero-moved handling retries with fresh persons) takes
            // over rather than merging stale source properties.
            if (moveResult.distinctIdsMoved.length !== expectedMoveCount) {
                throw new MergeFoldConflictError('folded merge moved an unexpected number of distinct ids')
            }
            this.recordOverrideCount('bothExistMove', moveResult.distinctIdsMoved.length)

            const addMessages: PersonMessage[] = []
            for (const pair of missingSources) {
                // See mergeSingle for the distinctIdVersion logic.
                const distinctIdVersion = 1
                this.recordOverrideCount('fold')
                addMessages.push(...(await tx.addDistinctId(person, pair.distinctId, distinctIdVersion)))
            }

            let deleteMessages: PersonMessage[] = []
            if (mergeSources.length > 0) {
                await tx.updateCohortsAndFeatureFlagsForMergeBatch(
                    teamId,
                    mergeSources.map((source) => source.id),
                    currentTarget.id,
                    this.targetDistinctId
                )
                deleteMessages = await tx.deletePersons(mergeSources, this.targetDistinctId)
            }

            if (this.tombstoneEnabled()) {
                await tx.releaseLifecycleMarks(lifecycleOpId, teamId, this.targetDistinctId)
            }
            return [person, [...updateMessages, ...moveResult.messages, ...addMessages, ...deleteMessages]]
        })

        this.flushOverrideCounts()
        mergeFoldExecutedCounter.inc()
        mergeFoldSizeHistogram.observe(this.request.sources.length)

        // The bootstrap's produce, when there was one, joins the fold's own
        // ack so the caller observes every message this merge produced.
        const foldAck = this.produceMessages(kafkaMessages)
        const kafkaAck = bootstrapAck ? joinAcks(bootstrapAck, foldAck) : foldAck
        for (const source of mergeSources) {
            // Same fire-and-forget contract as executeTransaction.
            void this.producePersonMergeEvent(source, mergedPerson).catch(() => {})
        }
        outcomes.push(...mergedSourceOutcomes)
        outcomes.push(
            ...missingSources.map(
                (pair): MergePersonsSourceResult => ({
                    sourceDistinctId: pair.distinctId,
                    outcome: 'attached',
                })
            )
        )
        return { survivor: mergedPerson, results: outcomes, kafkaAck }
    }

    private async mergePeople({
        mergeInto,
        mergeIntoDistinctId,
        otherPerson,
        otherPersonDistinctId,
    }: {
        mergeInto: InternalPerson
        mergeIntoDistinctId: string
        otherPerson: InternalPerson
        otherPersonDistinctId: string
    }): Promise<MergePersonsResult> {
        const olderCreatedAt = DateTime.min(mergeInto.created_at, otherPerson.created_at)

        // $merge_dangerously has no restrictions; $create_alias and $identify
        // will not merge a user who's already identified into anyone else.
        const mergeAllowed = this.request.allowIdentifiedSources || !otherPerson.is_identified
        if (!mergeAllowed) {
            return {
                survivor: mergeInto,
                results: [
                    {
                        sourceDistinctId: otherPersonDistinctId,
                        outcome: 'skipped_already_identified',
                        sourcePersonUuid: otherPerson.uuid,
                    },
                ],
            }
        }

        // How the merge works:
        // Merging properties:
        //   on key conflict we use the properties from the person provided as the first argument in identify or alias calls (mergeInto person),
        //   Note it's important for us to compute this before potentially swapping the persons for personID merging purposes in PoEEmbraceJoin mode
        // In case of PoE Embrace the join mode:
        //   we want to keep using the older person to reduce the number of partitions that need to be updated during squash
        //   to do that we'll swap otherPerson and mergeInto person (after properties merge computation!)
        //   additionally update person overrides table in postgres and clickhouse
        //   TODO: ^
        // If the merge fails:
        //   we'll roll back the transaction and then try from scratch in the origial order of persons provided for property merges
        //   that guarantees consistency of how properties are processed regardless of persons created_at timestamps and rollout state
        //   we're calling aliasDeprecated as we need to refresh the persons info completely first

        const mergedProperties: Properties = { ...otherPerson.properties, ...mergeInto.properties }
        const propertyUpdates = refineEventOps(this.request.eventOps, mergedProperties, this.policy.updateAllProperties)

        // Create a temporary person object to apply property updates to
        const tempPerson: InternalPerson = { ...mergeInto, properties: mergedProperties }
        const [updatedTempPerson, _] = applyEventPropertyUpdates(propertyUpdates, tempPerson)
        const properties = updatedTempPerson.properties

        const result = await this.handleMergeTransaction(
            mergeInto,
            mergeIntoDistinctId,
            otherPerson,
            otherPersonDistinctId,
            olderCreatedAt, // Keep the oldest created_at (i.e. the first time we've seen either person)
            properties
        )

        if (result.success) {
            return {
                survivor: result.person ?? null,
                results: [
                    {
                        sourceDistinctId: otherPersonDistinctId,
                        outcome: 'merged',
                        sourcePersonUuid: otherPerson.uuid,
                    },
                ],
                kafkaAck: result.kafkaAck,
            }
        }

        // A race that persisted through every retry: another merge kept
        // winning the persons. The merge drops; the caller emits the
        // race-condition warning and keeps the target as the survivor.
        if (result.error instanceof PersonMergeRaceConditionError) {
            return {
                survivor: mergeInto,
                results: [
                    {
                        sourceDistinctId: otherPersonDistinctId,
                        outcome: 'skipped_race',
                        sourcePersonUuid: otherPerson.uuid,
                    },
                ],
            }
        }

        const failedOutcome =
            result.error instanceof PersonMergeLimitExceededError
                ? ('skipped_move_limit' as const)
                : result.error instanceof SourcePersonHasDistinctIdsError
                  ? ('failed_source_has_distinct_ids' as const)
                  : result.error instanceof TargetPersonNotFoundError
                    ? ('failed_target_not_found' as const)
                    : result.error instanceof SourcePersonNotFoundError
                      ? ('failed_source_not_found' as const)
                      : ('error' as const)
        return {
            survivor: null,
            results: [
                {
                    sourceDistinctId: otherPersonDistinctId,
                    outcome: failedOutcome,
                    sourcePersonUuid: otherPerson.uuid,
                },
            ],
        }
    }

    private async executeTransaction(
        currentTargetPerson: InternalPerson,
        currentSourcePerson: InternalPerson,
        createdAt: DateTime,
        properties: Properties
    ): Promise<PersonMergeResult> {
        try {
            mergeTxnAttemptCounter
                .labels({
                    call: this.eventName, // $identify, $create_alias or $merge_dangerously
                    oldPersonIdentified: String(currentSourcePerson.is_identified),
                    newPersonIdentified: String(currentTargetPerson.is_identified),
                })
                .inc()

            this.discardOverrideCounts()
            const lifecycleOpId = lifecycleOpIdFromEvent(this.teamId, this.request.opId)
            const [mergedPerson, kafkaMessages] = await this.inTransaction('mergePeople', async (tx) => {
                // New-world merges claim both persons in the lifecycle mark table: at
                // most one live operation (merge or delete saga) may hold a person, so
                // neither can be tombstoned under this transaction. The marks say
                // nothing about tombstones committed before the claim, so assert both
                // persons are still live while holding them. Liveness checks are
                // separate statements because a claim that waited on the mark index
                // resumes with a stale snapshot.
                if (this.tombstoneEnabled()) {
                    await tx.claimLifecycleMarks(
                        lifecycleOpId,
                        currentTargetPerson.team_id,
                        [
                            {
                                personId: currentTargetPerson.id,
                                personUuid: currentTargetPerson.uuid,
                                role: 'target',
                            },
                            {
                                personId: currentSourcePerson.id,
                                personUuid: currentSourcePerson.uuid,
                                role: 'source',
                                ordinal: 0,
                            },
                        ],
                        this.targetDistinctId
                    )
                    if (!(await tx.isPersonLive(currentTargetPerson, this.targetDistinctId))) {
                        throw new TargetPersonNotFoundError('Target person was deleted concurrently')
                    }
                    if (!(await tx.isPersonLive(currentSourcePerson, this.targetDistinctId))) {
                        throw new SourcePersonNotFoundError('Source person was deleted concurrently')
                    }
                }
                const [person, updatePersonMessages] = await tx.updatePersonForMerge(
                    currentTargetPerson,
                    {
                        created_at: createdAt,
                        properties: properties,
                        is_identified: true,

                        // By using the max version between the two Persons, we ensure that if
                        // this Person is later split, we can use `this_person.version + 1` for
                        // any split-off Persons and know that *that* version will be higher than
                        // any previously deleted Person, and so the new Person row will "win" and
                        // "undelete" the Person.
                        //
                        // For example:
                        //  - Merge Person_1(version:7) into Person_2(version:2)
                        //      - Person_1 is deleted
                        //      - Person_2 attains version 8 via this code below
                        //  - Person_2 is later split, which attempts to re-create Person_1 by using
                        //    its `distinct_id` to generate the deterministic Person UUID.
                        //    That new Person_1 will have a version _at least_ as high as 8, and
                        //    so any previously existing rows in CH or otherwise from
                        //    Person_1(version:7) will "lose" to this new Person_1.
                        version: Math.max(currentTargetPerson.version, currentSourcePerson.version) + 1,
                    },
                    this.targetDistinctId
                )

                // Move distinct IDs first to establish ownership of the source person quickly.
                // This reduces contention when multiple concurrent merges target the same source,
                // as subsequent lookups via distinct ID will fail faster.
                const allDistinctIdMessages = await this.moveDistinctIdsBasedOnMode(
                    tx,
                    currentSourcePerson,
                    currentTargetPerson
                )

                // Update cohorts and feature flags after distinct IDs are moved.
                // The source person row still exists (deleted below), so FK constraints are satisfied.
                // TODO: Doesn't this table need to add updates to CH too?
                await tx.updateCohortsAndFeatureFlagsForMerge(
                    currentSourcePerson.team_id,
                    currentSourcePerson.id,
                    currentTargetPerson.id,
                    this.targetDistinctId
                )

                const deletePersonMessages = await tx.deletePerson(currentSourcePerson, this.targetDistinctId)
                if (this.tombstoneEnabled()) {
                    await tx.releaseLifecycleMarks(lifecycleOpId, this.teamId, this.targetDistinctId)
                }
                return [person, [...updatePersonMessages, ...allDistinctIdMessages, ...deletePersonMessages]]
            })

            this.flushOverrideCounts()
            mergeTxnSuccessCounter
                .labels({
                    call: this.eventName, // $identify, $create_alias or $merge_dangerously
                    oldPersonIdentified: String(currentSourcePerson.is_identified),
                    newPersonIdentified: String(currentTargetPerson.is_identified),
                })
                .inc()

            // Fire-and-forget after commit: the person_merge_events emission is detached from the ack
            // chain, so a produce failure can never block, replay, or crash ingestion.
            // producePersonMergeEvent is best-effort and never throws; the call-site catch is a safety
            // net that swallows an escaped rejection so a broken never-throws contract can't reach the
            // unhandledRejection handler and stop the service.
            const kafkaAck = this.produceMessages(kafkaMessages)
            void this.producePersonMergeEvent(currentSourcePerson, mergedPerson).catch(() => {})
            return mergeSuccess(mergedPerson, kafkaAck, true)
        } catch (error) {
            // Map exceptions to result types - these will cause transaction rollback
            if (error instanceof SourcePersonNotFoundError) {
                return mergeError(error)
            } else if (error instanceof TargetPersonNotFoundError) {
                return mergeError(error)
            } else if (error instanceof PersonMergeLimitExceededError) {
                return mergeError(error)
            } else if (error.code === '23503' || error instanceof PersonTombstoneBlockedError) {
                // A concurrent merge added a distinct ID to the source person after we've already
                // moved the distinct IDs we knew about, but before the delete executed — surfaced
                // as a foreign key violation by the hard delete, or as PersonTombstoneBlockedError
                // by the tombstone's live-mapping guard. The retry mechanism will:
                // 1. Refresh the source person data to see all distinct IDs (including newly added ones)
                // 2. Move ALL distinct IDs to the target person
                // 3. Successfully delete the now-empty source person
                return mergeError(
                    new SourcePersonHasDistinctIdsError(
                        'Cannot delete source person due to concurrent distinct ID additions'
                    )
                )
            } else {
                // Re-throw unexpected errors
                throw error
            }
        }
    }

    // Override-counter increments are buffered and flushed only after the enclosing
    // transaction commits: merges retry and roll back, and rolled-back rows must not
    // inflate a metric used for override-inflow capacity planning.
    private pendingOverrideCounts: { call: string; count: number }[] = []

    private recordOverrideCount(call: string, count: number = 1): void {
        if (count > 0) {
            this.pendingOverrideCounts.push({ call, count })
        }
    }

    private discardOverrideCounts(): void {
        this.pendingOverrideCounts = []
    }

    private flushOverrideCounts(): void {
        for (const { call, count } of this.pendingOverrideCounts) {
            mergeDistinctIdOverrideCounter.labels({ call }).inc(count)
        }
        this.pendingOverrideCounts = []
    }

    private async moveDistinctIdsBasedOnMode(
        tx: PersonsStoreTransactionForBatch,
        currentSourcePerson: InternalPerson,
        currentTargetPerson: InternalPerson
    ): Promise<PersonMessage[]> {
        if (this.request.mergeMode.type === 'SYNC') {
            if (!this.request.mergeMode.batchSize) {
                return await this.moveDistinctIdsWithLimit(tx, currentSourcePerson, currentTargetPerson, undefined)
            }
            return await this.moveDistinctIdsInBatches(
                tx,
                currentSourcePerson,
                currentTargetPerson,
                this.request.mergeMode.batchSize
            )
        } else {
            const limit = this.request.mergeMode.limit
            return await this.moveDistinctIdsWithLimit(tx, currentSourcePerson, currentTargetPerson, limit)
        }
    }

    private async moveDistinctIdsInBatches(
        tx: PersonsStoreTransactionForBatch,
        currentSourcePerson: InternalPerson,
        currentTargetPerson: InternalPerson,
        batchSize: number
    ): Promise<PersonMessage[]> {
        const allDistinctIdMessages: PersonMessage[] = []
        let hasMore = true
        let hasProcessedAnyDistinctIds = false

        while (hasMore) {
            const distinctIdResult = await tx.moveDistinctIds(
                currentSourcePerson,
                currentTargetPerson,
                this.targetDistinctId,
                batchSize
            )

            if (!distinctIdResult.success) {
                if (distinctIdResult.error === 'SourceNotFound') {
                    if (hasProcessedAnyDistinctIds) {
                        // Source person not found after we've already moved some distinct IDs
                        // This means we've moved all distinct IDs
                        hasMore = false
                        break
                    } else {
                        // Source person not found on first attempt - this is a real error
                        throw new SourcePersonNotFoundError('Source person no longer exists')
                    }
                } else if (distinctIdResult.error === 'TargetNotFound') {
                    throw new TargetPersonNotFoundError('Target person no longer exists')
                }
            } else {
                allDistinctIdMessages.push(...distinctIdResult.messages)
                hasProcessedAnyDistinctIds = true
                this.recordOverrideCount('bothExistMove', distinctIdResult.distinctIdsMoved.length)

                // Check if we moved fewer than the batch size, indicating we're done
                hasMore = distinctIdResult.distinctIdsMoved.length >= batchSize
            }
        }

        return allDistinctIdMessages
    }

    private async moveDistinctIdsWithLimit(
        tx: PersonsStoreTransactionForBatch,
        currentSourcePerson: InternalPerson,
        currentTargetPerson: InternalPerson,
        limit: number | undefined
    ): Promise<PersonMessage[]> {
        // Original behavior for LIMIT mode or SYNC without batchSize
        const distinctIdResult = await tx.moveDistinctIds(
            currentSourcePerson,
            currentTargetPerson,
            this.targetDistinctId,
            limit
        )

        if (!distinctIdResult.success) {
            if (distinctIdResult.error === 'SourceNotFound') {
                throw new SourcePersonNotFoundError('Source person no longer exists')
            } else if (distinctIdResult.error === 'TargetNotFound') {
                throw new TargetPersonNotFoundError('Target person no longer exists')
            }
        }

        const allDistinctIdMessages = distinctIdResult.success ? distinctIdResult.messages : []

        // If moved count equals the per-call limit, verify if it's a partial move by checking remaining IDs
        const movedCount = distinctIdResult.success ? distinctIdResult.distinctIdsMoved.length : 0
        const hitLimit = limit ? movedCount >= limit : false

        if (hitLimit) {
            const remaining = await tx.fetchPersonDistinctIds(currentSourcePerson, this.targetDistinctId, 1)
            if (remaining.length > 0) {
                personMergeFailureCounter.labels({ call: this.eventName }).inc()
                // Drop the event by throwing an error that the pipeline will map to DLQ/no-retry
                logger.error('🤔', 'person merge move limit hit', {
                    team_id: this.teamId,
                    distinct_id: this.targetDistinctId,
                })
                throw new PersonMergeLimitExceededError('person_merge_move_limit_hit')
            }
        }
        this.recordOverrideCount('bothExistMove', movedCount)

        return allDistinctIdMessages
    }

    private async handleMergeTransaction(
        targetPerson: InternalPerson,
        targetDistinctId: string,
        sourcePerson: InternalPerson,
        sourceDistinctId: string,
        createdAt: DateTime,
        properties: Properties,
        maxRetries: number = 5
    ): Promise<PersonMergeResult> {
        let currentTargetPerson = targetPerson
        let currentSourcePerson = sourcePerson

        for (let attempt = 0; attempt <= maxRetries; attempt++) {
            const result = await this.executeTransaction(
                currentTargetPerson,
                currentSourcePerson,
                createdAt,
                properties
            )

            if (result.success) {
                return result
            }

            // Handle retryable errors
            if (attempt < maxRetries) {
                if (
                    result.error instanceof SourcePersonNotFoundError ||
                    result.error instanceof SourcePersonHasDistinctIdsError
                ) {
                    const refreshedPerson = await this.refreshPersonData(
                        sourceDistinctId,
                        currentSourcePerson.id,
                        attempt,
                        'source'
                    )

                    if (!refreshedPerson) {
                        return mergeSuccess(currentTargetPerson, Promise.resolve(), true)
                    }

                    currentSourcePerson = refreshedPerson
                    continue
                } else if (result.error instanceof TargetPersonNotFoundError) {
                    const refreshedPerson = await this.refreshPersonData(
                        targetDistinctId,
                        currentTargetPerson.id,
                        attempt,
                        'target'
                    )

                    if (!refreshedPerson) {
                        return mergeSuccess(currentTargetPerson, Promise.resolve(), true)
                    }

                    currentTargetPerson = refreshedPerson
                    continue
                } else {
                    // Non-retryable error, return the failure result
                    return result
                }
            } else {
                // Max retries reached, return the failure result
                return result
            }
        }

        // This should never be reached, but add fallback for race condition
        return mergeError(
            new PersonMergeRaceConditionError(
                `Failed to merge persons due to concurrent merges, ` +
                    `source person: ${sourcePerson.id}, target person: ${targetPerson.id}, team: ${this.teamId} ` +
                    `source distinct id: ${sourceDistinctId}, target distinct id: ${targetDistinctId}`
            )
        )
    }

    private async refreshPersonData(
        distinctId: string,
        currentPersonId: string,
        attempt: number,
        personType: 'source' | 'target'
    ): Promise<InternalPerson | null> {
        logger.info(`${personType} person not found, retrying with fresh data`, {
            [`${personType}PersonId`]: currentPersonId,
            teamId: this.teamId,
            attempt,
            distinctId,
        })

        // Purge the mapping so the refresh reads committed state instead of the cached person.
        this.store.removeDistinctIdFromCache(this.teamId, distinctId)

        // Fetch the refreshed person data using the new distinct ID
        const refreshedPerson = await this.store.fetchForUpdate(this.teamId, distinctId, this.batchId)

        if (!refreshedPerson) {
            logger.info(`${personType} person no longer exists after refresh, skipping merge`, {
                [`${personType}PersonId`]: currentPersonId,
                teamId: this.teamId,
                attempt,
            })
            return null
        }

        return refreshedPerson
    }
}
