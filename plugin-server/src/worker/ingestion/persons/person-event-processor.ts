import LRU from 'lru-cache'
import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { ONE_HOUR } from '../../../config/constants'
import { PipelineResult, dlq, ok, redirect } from '../../../ingestion/pipelines/results'
import { InternalPerson, Person } from '../../../types'
import { logger } from '../../../utils/logger'
import { uuidFromDistinctId } from '../person-uuid'
import { PersonContext } from './person-context'
import { PersonMergeService } from './person-merge-service'
import { PersonMergeLimitExceededError, PersonMergeRaceConditionError } from './person-merge-types'
import { PersonPropertyService } from './person-property-service'

// Tracks whether we know we've already inserted a `posthog_personlessdistinctid` for the given
// (team_id, distinct_id) pair. If we have, then we can skip the INSERT attempt.
// TODO: Move this out of module scope, we don't currently have a clean place (outside of the Hub)
// to stash longer lived objects like caches. For now it's not important.
const PERSONLESS_DISTINCT_ID_INSERTED_CACHE = new LRU<string, boolean>({
    max: 10_000,
    maxAge: ONE_HOUR * 24, // cache up to 24h
    updateAgeOnGet: true,
})

/**
 * Main orchestrator for person processing operations.
 * This class coordinates between PersonPropertyService and PersonMergeService
 * to handle the different person processing flows
 */
export class PersonEventProcessor {
    constructor(
        private context: PersonContext,
        private propertyService: PersonPropertyService,
        private mergeService: PersonMergeService,
        private forceDisablePersonProcessing: boolean = false
    ) {}

    async processEvent(): Promise<[PipelineResult<Person>, Promise<void>]> {
        if (!this.context.processPerson) {
            return await this.handlePersonlessMode()
        }

        // First, handle any identify/alias/merge operations
        const mergeResult = await this.mergeService.handleIdentifyOrAlias()

        let personFromMerge: InternalPerson | undefined = undefined
        let identifyOrAliasKafkaAck: Promise<void> = Promise.resolve()
        let needsPersonUpdate = true

        if (mergeResult.success) {
            personFromMerge = mergeResult.person
            identifyOrAliasKafkaAck = mergeResult.kafkaAck
            needsPersonUpdate = mergeResult.needsPersonUpdate
        } else {
            const errorResult = this.handleMergeError(mergeResult.error, this.context.event)
            if (errorResult) {
                return [errorResult, Promise.resolve()]
            }
            logger.warn('Merge operation failed, continuing with normal property updates', {
                error: mergeResult.error.message,
                team_id: this.context.team.id,
            })
        }

        if (personFromMerge && needsPersonUpdate) {
            // Try to shortcut if we have the person from identify or alias
            try {
                const [updatedPerson, updateKafkaAck] =
                    await this.propertyService.updatePersonProperties(personFromMerge)
                return [ok(updatedPerson), Promise.all([identifyOrAliasKafkaAck, updateKafkaAck]).then(() => undefined)]
            } catch (error) {
                // Shortcut didn't work, swallow the error and try normal retry loop below
                logger.debug('🔁', `failed update after adding distinct IDs, retrying`, { error })
            }
        }

        if (personFromMerge && !needsPersonUpdate) {
            return [ok(personFromMerge), identifyOrAliasKafkaAck]
        }

        // Handle regular property updates
        const [updatedPerson, updateKafkaAck] = await this.propertyService.handleUpdate()
        return [ok(updatedPerson), Promise.all([identifyOrAliasKafkaAck, updateKafkaAck]).then(() => undefined)]
    }

    private async handlePersonlessMode(): Promise<[PipelineResult<Person>, Promise<void>]> {
        // If forceDisablePersonProcessing is true, skip all personless processing and just return a fake person
        if (this.forceDisablePersonProcessing) {
            return [ok(this.createFakePerson()), Promise.resolve()]
        }

        let existingPerson = await this.context.personStore.fetchForChecking(
            this.context.team.id,
            this.context.distinctId
        )

        if (!existingPerson) {
            // See the comment in `mergeDistinctIds`. We are inserting a row into `posthog_personlessdistinctid`
            // to note that this Distinct ID has been used in "personless" mode. This is necessary
            // so that later, during a merge, we can decide whether we need to write out an override
            // or not.

            const personlessDistinctIdCacheKey = `${this.context.team.id}|${this.context.distinctId}`
            if (!PERSONLESS_DISTINCT_ID_INSERTED_CACHE.get(personlessDistinctIdCacheKey)) {
                const personIsMerged = await this.context.personStore.addPersonlessDistinctId(
                    this.context.team.id,
                    this.context.distinctId
                )

                // We know the row is in PG now, and so future events for this Distinct ID can
                // skip the PG I/O.
                PERSONLESS_DISTINCT_ID_INSERTED_CACHE.set(personlessDistinctIdCacheKey, true)

                if (personIsMerged) {
                    // If `personIsMerged` comes back `true`, it means the `posthog_personlessdistinctid`
                    // has been updated by a merge (either since we called `fetchPerson` above, plus
                    // replication lag). We need to check `fetchPerson` again (this time using the leader)
                    // so that we properly associate this event with the Person we got merged into.
                    existingPerson = await this.context.personStore.fetchForUpdate(
                        this.context.team.id,
                        this.context.distinctId
                    )
                }
            }
        }

        if (existingPerson) {
            const person = existingPerson as Person

            // Ensure person properties don't propagate elsewhere, such as onto the event itself.
            person.properties = {}

            // If the team has opted out then we never force the upgrade.
            const teamHasNotOptedOut = !this.context.team.person_processing_opt_out

            if (teamHasNotOptedOut && this.context.timestamp > person.created_at.plus({ minutes: 1 })) {
                // See documentation on the field.
                //
                // Note that we account for timestamp vs person creation time (with a little
                // padding for good measure) to account for ingestion lag. It's possible for
                // events to be processed after person creation even if they were sent prior
                // to person creation, and the user did nothing wrong in that case.
                person.force_upgrade = true
            }

            return [ok(person), Promise.resolve()]
        }

        const fakePerson = this.createFakePerson()
        return [ok(fakePerson), Promise.resolve()]
    }

    private createFakePerson(): Person {
        // We need a value from the `person_created_column` in ClickHouse. This should be
        // hidden from users for events without a real person, anyway. It's slightly offset
        // from the 0 date (by 5 seconds) in order to assist in debugging by being
        // harmlessly distinct from Unix UTC "0".
        const createdAt = DateTime.utc(1970, 1, 1, 0, 0, 5)

        return {
            team_id: this.context.team.id,
            properties: {},
            uuid: uuidFromDistinctId(this.context.team.id, this.context.distinctId),
            created_at: createdAt,
        }
    }

    getContext(): PersonContext {
        return this.context
    }

    private handleMergeError(error: unknown, event: PluginEvent): PipelineResult<Person> | null {
        const mergeMode = this.context.mergeMode

        if (error instanceof PersonMergeLimitExceededError) {
            logger.info('Merge limit exceeded', {
                mode: mergeMode.type,
                team_id: this.context.team.id,
                distinct_id: this.context.distinctId,
            })

            // Action depends on the configured merge mode
            switch (mergeMode.type) {
                case 'ASYNC':
                    logger.info('Redirecting to async merge topic', {
                        topic: mergeMode.topic,
                        team_id: event.team_id,
                        distinct_id: event.distinct_id,
                    })
                    return redirect('Event redirected to async merge topic', mergeMode.topic)
                case 'LIMIT':
                    logger.warn('Limit exceeded, will be sent to DLQ', {
                        limit: mergeMode.limit,
                        team_id: event.team_id,
                        distinct_id: event.distinct_id,
                    })
                    return dlq('Merge limit exceeded', error)
                case 'SYNC':
                    // SYNC mode should never hit limits - this indicates a bug
                    logger.error('Unexpected limit exceeded in SYNC mode - this should not happen', {
                        team_id: event.team_id,
                        distinct_id: event.distinct_id,
                        mergeMode: mergeMode,
                    })
                    throw error
            }
        } else if (error instanceof PersonMergeRaceConditionError) {
            logger.warn('Race condition detected, ignoring merge', {
                error: error.message,
                team_id: this.context.team.id,
                distinct_id: this.context.distinctId,
            })
            return null // Continue with normal processing
        } else {
            // Unknown errors should be thrown - they indicate bugs or unexpected conditions
            logger.error('Unknown merge error - throwing to surface the issue', {
                mergeMode: mergeMode.type,
                error: error instanceof Error ? error.message : String(error),
                team_id: this.context.team.id,
                distinct_id: this.context.distinctId,
            })
            throw error
        }
    }
}
