import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { Properties } from '@posthog/plugin-scaffold'

import { TopicMessage } from '../../../kafka/producer'
import { InternalPerson } from '../../../types'
import { timeoutGuard } from '../../../utils/db/utils'
import { logger } from '../../../utils/logger'
import { captureException } from '../../../utils/posthog'
import { promiseRetry } from '../../../utils/retries'
import { captureIngestionWarning } from '../utils'
import { personMergeFailureCounter } from './metrics'
import { PersonContext } from './person-context'
import { PersonCreateService } from './person-create-service'
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
import { applyEventPropertyUpdates, computeEventPropertyUpdates } from './person-update'
import { PersonsStoreTransaction } from './persons-store-transaction'

export const mergeFinalFailuresCounter = new Counter({
    name: 'person_merge_final_failure_total',
    help: 'Number of person merge final failures.',
})

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
// used to prevent identify from being used with generic IDs
// that we can safely assume stem from a bug or mistake
const BARE_CASE_INSENSITIVE_ILLEGAL_IDS = [
    'anonymous',
    'guest',
    'distinctid',
    'distinct_id',
    'id',
    'not_authenticated',
    'email',
    'undefined',
    'true',
    'false',
]

const BARE_CASE_SENSITIVE_ILLEGAL_IDS = ['[object Object]', 'NaN', 'None', 'none', 'null', '0', 'undefined']

// we have seen illegal ids received but wrapped in double quotes
// to protect ourselves from this we'll add the single- and double-quoted versions of the illegal ids
const singleQuoteIds = (ids: string[]) => ids.map((id) => `'${id}'`)
const doubleQuoteIds = (ids: string[]) => ids.map((id) => `"${id}"`)

// some ids are illegal regardless of casing
// while others are illegal only when cased
// so, for example, we want to forbid `NaN` but not `nan`
// but, we will forbid `uNdEfInEd` and `undefined`
const CASE_INSENSITIVE_ILLEGAL_IDS = new Set(
    BARE_CASE_INSENSITIVE_ILLEGAL_IDS.concat(singleQuoteIds(BARE_CASE_INSENSITIVE_ILLEGAL_IDS)).concat(
        doubleQuoteIds(BARE_CASE_INSENSITIVE_ILLEGAL_IDS)
    )
)

const CASE_SENSITIVE_ILLEGAL_IDS = new Set(
    BARE_CASE_SENSITIVE_ILLEGAL_IDS.concat(singleQuoteIds(BARE_CASE_SENSITIVE_ILLEGAL_IDS)).concat(
        doubleQuoteIds(BARE_CASE_SENSITIVE_ILLEGAL_IDS)
    )
)

export const isDistinctIdIllegal = (id: string): boolean => {
    const trimmed = id.trim()
    return trimmed === '' || CASE_INSENSITIVE_ILLEGAL_IDS.has(id.toLowerCase()) || CASE_SENSITIVE_ILLEGAL_IDS.has(id)
}

/**
 * Service responsible for handling person merging operations (identify, alias, merge).
 * Extracted from PersonState to focus on merge-specific logic.
 */
export class PersonMergeService {
    private personCreateService: PersonCreateService
    constructor(private context: PersonContext) {
        this.personCreateService = new PersonCreateService(context)
    }

    async handleIdentifyOrAlias(): Promise<PersonMergeResult> {
        /**
         * strategy:
         *   - if the two distinct ids passed don't match and aren't illegal, then mark `is_identified` to be true for the `distinct_id` person
         *   - if a person doesn't exist for either distinct id passed we create the person with both ids
         *   - if only one person exists we add the other distinct id
         *   - if the distinct ids belong to different already existing persons we try to merge them:
         *     - the merge is blocked if the other distinct id (`anon_distinct_id` or `alias` event property) person has `is_identified` true.
         *     - we merge into `distinct_id` person:
         *       - both distinct ids used in the future will map to the person id that was associated with `distinct_id` before
         *       - if person property was defined for both we'll use `distinct_id` person's property going forward
         */
        const timeout = timeoutGuard('Still running "handleIdentifyOrAlias". Timeout warning after 30 sec!')
        try {
            if (
                ['$create_alias', '$merge_dangerously'].includes(this.context.event.event) &&
                this.context.eventProperties['alias']
            ) {
                return await this.merge(
                    String(this.context.eventProperties['alias']),
                    this.context.distinctId,
                    this.context.team.id,
                    this.context.timestamp
                )
            } else if (
                this.context.event.event === '$identify' &&
                '$anon_distinct_id' in this.context.eventProperties
            ) {
                return await this.merge(
                    String(this.context.eventProperties['$anon_distinct_id']),
                    this.context.distinctId,
                    this.context.team.id,
                    this.context.timestamp
                )
            }
        } catch (e) {
            captureException(e, {
                tags: { team_id: this.context.team.id, pipeline_step: 'processPersonsStep' },
                extra: {
                    location: 'handleIdentifyOrAlias',
                    distinctId: this.context.distinctId,
                    anonId: String(this.context.eventProperties['$anon_distinct_id']),
                    alias: String(this.context.eventProperties['alias']),
                },
            })
            mergeFinalFailuresCounter.inc()
            logger.error('handleIdentifyOrAlias failed', {
                error: e,
                team_id: this.context.team.id,
                distinctId: this.context.distinctId,
                event_name: this.context.event.event,
                anon_distinct_id: String(this.context.eventProperties['$anon_distinct_id']),
                alias: String(this.context.eventProperties['alias']),
            })
        } finally {
            clearTimeout(timeout)
        }
        // For non-merge events or when no merge conditions are met, return success with no person
        return mergeSuccess(undefined, Promise.resolve())
    }

    public async merge(
        otherPersonDistinctId: string,
        mergeIntoDistinctId: string,
        teamId: number,
        timestamp: DateTime
    ): Promise<PersonMergeResult> {
        // No reason to alias person against itself. Done by posthog-node when updating user properties
        if (mergeIntoDistinctId === otherPersonDistinctId) {
            // Create a success result with undefined person to indicate no merge was needed
            return mergeSuccess(undefined, Promise.resolve())
        }
        if (isDistinctIdIllegal(mergeIntoDistinctId)) {
            await captureIngestionWarning(
                this.context.kafkaProducer,
                teamId,
                'cannot_merge_with_illegal_distinct_id',
                {
                    illegalDistinctId: mergeIntoDistinctId,
                    otherDistinctId: otherPersonDistinctId,
                    eventUuid: this.context.event.uuid,
                },
                { alwaysSend: true }
            )
            return mergeSuccess(undefined, Promise.resolve())
        }
        if (isDistinctIdIllegal(otherPersonDistinctId)) {
            await captureIngestionWarning(
                this.context.kafkaProducer,
                teamId,
                'cannot_merge_with_illegal_distinct_id',
                {
                    illegalDistinctId: otherPersonDistinctId,
                    otherDistinctId: mergeIntoDistinctId,
                    eventUuid: this.context.event.uuid,
                },
                { alwaysSend: true }
            )
            return mergeSuccess(undefined, Promise.resolve())
        }

        const result = await promiseRetry(
            () => this.mergeDistinctIds(otherPersonDistinctId, mergeIntoDistinctId, teamId, timestamp),
            'merge_distinct_ids'
        )
        return result
    }

    private async mergeDistinctIds(
        otherPersonDistinctId: string,
        mergeIntoDistinctId: string,
        teamId: number,
        timestamp: DateTime
    ): Promise<PersonMergeResult> {
        this.context.updateIsIdentified = true

        const otherPerson = await this.context.personStore.fetchForUpdate(teamId, otherPersonDistinctId)
        const mergeIntoPerson = await this.context.personStore.fetchForUpdate(teamId, mergeIntoDistinctId)

        // A note about the `distinctIdVersion` logic you'll find below:
        //
        // Historically, we always INSERT-ed new `posthog_persondistinctid` rows with `version=0`.
        // Overrides are only created when the version is > 0, see:
        //   https://github.com/PostHog/posthog/blob/92e17ce307a577c4233d4ab252eebc6c2207a5ee/posthog/models/person/sql.py#L269-L287
        //
        // With the addition of optional person profile processing, we are no longer creating
        // `posthog_persondistinctid` and `posthog_person` rows when $process_person_profile=false.
        // This means that at merge time, it's possible this `distinct_id` and its deterministically
        // generated `person.uuid` has already been used for events in ClickHouse, but they have no
        // corresponding rows in the `posthog_persondistinctid` or `posthog_person` tables.
        //
        // For this reason, $process_person_profile=false write to the `posthog_personlessdistinctid`
        // table just to note that a given Distinct ID was used for "personless" mode. Then, during
        // our merges transactions below, we do two things:
        //   1. We check whether a row exists in `posthog_personlessdistinctid` for that Distinct ID,
        //      if so, we need to write out `posthog_persondistinctid` rows with `version=1` so that
        //      an override is created in ClickHouse which will associate the old "personless" events
        //      with the Person UUID they were merged into.
        //   2. We insert and/or update the `posthog_personlessdistinctid` ourselves, to mark that
        //      the Distinct ID has been merged. This is important so that an event being processed
        //      concurrently for that Distinct ID doesn't emit an event and _miss_ that a different
        //      Person UUID needs to be used now. (See the `processPerson` code in `update` for more.)

        if ((otherPerson && !mergeIntoPerson) || (!otherPerson && mergeIntoPerson)) {
            // Only one of the two Distinct IDs points at an existing Person

            const [existingPerson, distinctIdToAdd] = (() => {
                if (otherPerson) {
                    return [otherPerson!, mergeIntoDistinctId]
                } else {
                    return [mergeIntoPerson!, otherPersonDistinctId]
                }
            })()

            return await this.context.personStore.inTransaction('mergeDistinctIds-OneExists', async (tx) => {
                // See comment above about `distinctIdVersion`
                const insertedDistinctId = await tx.addPersonlessDistinctIdForMerge(
                    this.context.team.id,
                    distinctIdToAdd
                )
                const distinctIdVersion = insertedDistinctId ? 0 : 1

                const kafkaMessages = await tx.addDistinctId(existingPerson, distinctIdToAdd, distinctIdVersion)
                await this.context.kafkaProducer.queueMessages(kafkaMessages)
                return mergeSuccess(existingPerson, Promise.resolve())
            })
        } else if (otherPerson && mergeIntoPerson) {
            // Both Distinct IDs point at an existing Person

            if (otherPerson.id == mergeIntoPerson.id) {
                // Nothing to do, they are the same Person
                return mergeSuccess(mergeIntoPerson, Promise.resolve())
            }

            const result = await this.mergePeople({
                mergeInto: mergeIntoPerson,
                mergeIntoDistinctId: mergeIntoDistinctId,
                otherPerson: otherPerson,
                otherPersonDistinctId: otherPersonDistinctId,
            })

            return result
        } else {
            // Neither Distinct ID points at an existing Person

            let distinctId1 = mergeIntoDistinctId
            let distinctId2 = otherPersonDistinctId

            return await this.context.personStore.inTransaction('mergeDistinctIds-NeitherExist', async (tx) => {
                // See comment above about `distinctIdVersion`
                const insertedDistinctId1 = await tx.addPersonlessDistinctIdForMerge(this.context.team.id, distinctId1)

                // See comment above about `distinctIdVersion`
                const insertedDistinctId2 = await tx.addPersonlessDistinctIdForMerge(this.context.team.id, distinctId2)

                // `createPerson` uses the first Distinct ID provided to generate the Person
                // UUID. That means the first Distinct ID definitely doesn't need an override,
                // and can always use version 0. Below, we exhaust all of the options to decide
                // whether we can optimize away an override by doing a swap, or whether we
                // need to actually write an override. (But mostly we're being verbose for
                // documentation purposes)
                let distinctId2Version = 0
                if (insertedDistinctId1 && insertedDistinctId2) {
                    // We were the first to insert both (neither was used for Personless), so we
                    // can use either as the primary Person UUID and create no overrides.
                } else if (insertedDistinctId1 && !insertedDistinctId2) {
                    // We created 1, but 2 was already used for Personless. Let's swap so
                    // that 2 can be the primary Person UUID and no override is needed.
                    ;[distinctId1, distinctId2] = [distinctId2, distinctId1]
                } else if (!insertedDistinctId1 && insertedDistinctId2) {
                    // We created 2, but 1 was already used for Personless, so we want to
                    // use 1 as the primary Person UUID so that no override is needed.
                } else if (!insertedDistinctId1 && !insertedDistinctId2) {
                    // Both were used in Personless mode, so there is no more-correct choice of
                    // primary Person UUID to make here, and we need to drop an override by
                    // using version = 1 for Distinct ID 2.
                    distinctId2Version = 1
                }

                // The first Distinct ID is used to create the new Person's UUID, and so it
                // never needs an override.
                const distinctId1Version = 0

                const [person, _] = await this.personCreateService.createPerson(
                    // TODO: in this case we could skip the properties updates later
                    timestamp,
                    this.context.eventProperties['$set'] || {},
                    this.context.eventProperties['$set_once'] || {},
                    teamId,
                    null,
                    true,
                    this.context.event.uuid,
                    [
                        { distinctId: distinctId1, version: distinctId1Version },
                        { distinctId: distinctId2, version: distinctId2Version },
                    ],
                    tx
                )
                return mergeSuccess(person, Promise.resolve())
            })
        }
    }

    public async mergePeople({
        mergeInto,
        mergeIntoDistinctId,
        otherPerson,
        otherPersonDistinctId,
    }: {
        mergeInto: InternalPerson
        mergeIntoDistinctId: string
        otherPerson: InternalPerson
        otherPersonDistinctId: string
    }): Promise<PersonMergeResult> {
        const olderCreatedAt = DateTime.min(mergeInto.created_at, otherPerson.created_at)
        const mergeAllowed = this.isMergeAllowed(otherPerson)

        // If merge isn't allowed, we will ignore it, log an ingestion warning and return success with original person
        if (!mergeAllowed) {
            await captureIngestionWarning(
                this.context.kafkaProducer,
                this.context.team.id,
                'cannot_merge_already_identified',
                {
                    sourcePersonDistinctId: otherPersonDistinctId,
                    targetPersonDistinctId: mergeIntoDistinctId,
                    eventUuid: this.context.event.uuid,
                },
                { alwaysSend: true }
            )
            logger.warn('🤔', 'refused to merge an already identified user via an $identify or $create_alias call', {
                team_id: this.context.team.id,
            })
            return mergeSuccess(mergeInto, Promise.resolve())
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
        const propertyUpdates = computeEventPropertyUpdates(this.context.event, mergedProperties)

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
            return result
        }

        // Handle specific error types
        if (result.error instanceof PersonMergeRaceConditionError) {
            await captureIngestionWarning(
                this.context.kafkaProducer,
                this.context.team.id,
                'merge_race_condition',
                {
                    sourcePersonDistinctId: otherPersonDistinctId,
                    targetPersonDistinctId: mergeIntoDistinctId,
                    eventUuid: this.context.event.uuid,
                },
                { alwaysSend: true }
            )
            logger.warn('🤔', 'merge race condition detected, too many concurrent merges', {
                team_id: this.context.team.id,
            })
            return mergeSuccess(mergeInto, Promise.resolve())
        }

        // For other errors (PersonMergeLimitExceededError, etc.), return the error result
        return result
    }

    private isMergeAllowed(mergeFrom: InternalPerson): boolean {
        // $merge_dangerously has no restrictions
        // $create_alias and $identify will not merge a user who's already identified into anyone else
        return this.context.event.event === '$merge_dangerously' || !mergeFrom.is_identified
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
                    call: this.context.event.event, // $identify, $create_alias or $merge_dangerously
                    oldPersonIdentified: String(currentSourcePerson.is_identified),
                    newPersonIdentified: String(currentTargetPerson.is_identified),
                })
                .inc()

            const [mergedPerson, kafkaMessages] = await this.context.personStore.inTransaction(
                'mergePeople',
                async (tx) => {
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
                        this.context.distinctId
                    )

                    // Merge the distinct IDs
                    // TODO: Doesn't this table need to add updates to CH too?
                    await tx.updateCohortsAndFeatureFlagsForMerge(
                        currentSourcePerson.team_id,
                        currentSourcePerson.id,
                        currentTargetPerson.id,
                        this.context.distinctId
                    )

                    const allDistinctIdMessages = await this.moveDistinctIdsBasedOnMode(
                        tx,
                        currentSourcePerson,
                        currentTargetPerson
                    )

                    const deletePersonMessages = await tx.deletePerson(currentSourcePerson, this.context.distinctId)
                    return [person, [...updatePersonMessages, ...allDistinctIdMessages, ...deletePersonMessages]]
                }
            )

            mergeTxnSuccessCounter
                .labels({
                    call: this.context.event.event, // $identify, $create_alias or $merge_dangerously
                    oldPersonIdentified: String(currentSourcePerson.is_identified),
                    newPersonIdentified: String(currentTargetPerson.is_identified),
                })
                .inc()

            const kafkaAck = this.context.kafkaProducer.queueMessages(kafkaMessages)
            return mergeSuccess(mergedPerson, kafkaAck)
        } catch (error) {
            // Map exceptions to result types - these will cause transaction rollback
            if (error instanceof SourcePersonNotFoundError) {
                return mergeError(error)
            } else if (error instanceof TargetPersonNotFoundError) {
                return mergeError(error)
            } else if (error instanceof PersonMergeLimitExceededError) {
                return mergeError(error)
            } else if (error.code === '23503') {
                // Foreign key constraint violation when attempting to delete the source person.
                // This occurs when a concurrent merge operation adds a distinct ID to the source person
                // after we've already moved the distinct IDs we knew about, but before the DELETE executes.
                // The retry mechanism will:
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

    private async moveDistinctIdsBasedOnMode(
        tx: PersonsStoreTransaction,
        currentSourcePerson: InternalPerson,
        currentTargetPerson: InternalPerson
    ): Promise<TopicMessage[]> {
        if (this.context.mergeMode.type === 'SYNC') {
            if (!this.context.mergeMode.batchSize) {
                return await this.moveDistinctIdsWithLimit(tx, currentSourcePerson, currentTargetPerson, undefined)
            }
            return await this.moveDistinctIdsInBatches(
                tx,
                currentSourcePerson,
                currentTargetPerson,
                this.context.mergeMode.batchSize
            )
        } else {
            const limit = this.context.mergeMode.limit
            return await this.moveDistinctIdsWithLimit(tx, currentSourcePerson, currentTargetPerson, limit)
        }
    }

    private async moveDistinctIdsInBatches(
        tx: PersonsStoreTransaction,
        currentSourcePerson: InternalPerson,
        currentTargetPerson: InternalPerson,
        batchSize: number
    ): Promise<TopicMessage[]> {
        const allDistinctIdMessages: TopicMessage[] = []
        let hasMore = true
        let hasProcessedAnyDistinctIds = false

        while (hasMore) {
            const distinctIdResult = await tx.moveDistinctIds(
                currentSourcePerson,
                currentTargetPerson,
                this.context.distinctId,
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

                // Check if we moved fewer than the batch size, indicating we're done
                hasMore = distinctIdResult.distinctIdsMoved.length >= batchSize
            }
        }

        return allDistinctIdMessages
    }

    private async moveDistinctIdsWithLimit(
        tx: PersonsStoreTransaction,
        currentSourcePerson: InternalPerson,
        currentTargetPerson: InternalPerson,
        limit: number | undefined
    ): Promise<TopicMessage[]> {
        // Original behavior for LIMIT mode or SYNC without batchSize
        const distinctIdResult = await tx.moveDistinctIds(
            currentSourcePerson,
            currentTargetPerson,
            this.context.distinctId,
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
            const remaining = await tx.fetchPersonDistinctIds(currentSourcePerson, this.context.distinctId, 1)
            if (remaining.length > 0) {
                personMergeFailureCounter.labels({ call: this.context.event.event }).inc()
                // Drop the event by throwing an error that the pipeline will map to DLQ/no-retry
                logger.error('🤔', 'person merge move limit hit', {
                    team_id: this.context.team.id,
                    distinct_id: this.context.distinctId,
                })
                throw new PersonMergeLimitExceededError('person_merge_move_limit_hit')
            }
        }

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
                        return mergeSuccess(currentTargetPerson, Promise.resolve())
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
                        return mergeSuccess(currentTargetPerson, Promise.resolve())
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
                    `source person: ${sourcePerson.id}, target person: ${targetPerson.id}, team: ${this.context.team.id} ` +
                    `source distinct id: ${sourceDistinctId}, target distinct id: ${targetDistinctId}`
            )
        )
    }

    public async addDistinctId(
        person: InternalPerson,
        distinctId: string,
        version: number,
        tx?: PersonsStoreTransaction
    ): Promise<void> {
        const kafkaMessages = await (tx || this.context.personStore).addDistinctId(person, distinctId, version)
        await this.context.kafkaProducer.queueMessages(kafkaMessages)
    }

    private async refreshPersonData(
        distinctId: string,
        currentPersonId: string,
        attempt: number,
        personType: 'source' | 'target'
    ): Promise<InternalPerson | null> {
        logger.info(`${personType} person not found, retrying with fresh data`, {
            [`${personType}PersonId`]: currentPersonId,
            teamId: this.context.team.id,
            attempt,
            distinctId,
        })

        // Remove the distinct ID from the cache so that we don't try to use it again, if the store is the batch writing store
        // TODO: this should be removed once we clean up the person store code
        this.context.personStore.removeDistinctIdFromCache(this.context.team.id, distinctId)

        // Fetch the refreshed person data using the new distinct ID
        const refreshedPerson = await this.context.personStore.fetchForUpdate(this.context.team.id, distinctId)

        if (!refreshedPerson) {
            logger.info(`${personType} person no longer exists after refresh, skipping merge`, {
                [`${personType}PersonId`]: currentPersonId,
                teamId: this.context.team.id,
                attempt,
            })
            return null
        }

        return refreshedPerson
    }

    public getUpdateIsIdentified(): boolean {
        return this.context.updateIsIdentified
    }

    getContext(): PersonContext {
        return this.context
    }
}
