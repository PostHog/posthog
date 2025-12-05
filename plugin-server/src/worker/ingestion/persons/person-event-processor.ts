import { PluginEvent } from '@posthog/plugin-scaffold'

import { PipelineResult, dlq, ok, redirect } from '../../../ingestion/pipelines/results'
import { InternalPerson, Person } from '../../../types'
import { logger } from '../../../utils/logger'
import { PersonContext } from './person-context'
import { PersonMergeService } from './person-merge-service'
import { PersonMergeLimitExceededError, PersonMergeRaceConditionError } from './person-merge-types'
import { PersonPropertyService } from './person-property-service'

/**
 * Main orchestrator for person processing operations.
 * This class coordinates between PersonPropertyService and PersonMergeService
 * to handle the different person processing flows
 */
export class PersonEventProcessor {
    constructor(
        private context: PersonContext,
        private propertyService: PersonPropertyService,
        private mergeService: PersonMergeService
    ) {}

    async processEvent(): Promise<[PipelineResult<Person>, Promise<void>]> {
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
