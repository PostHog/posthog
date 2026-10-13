import { ASYNC_OUTPUT, AsyncOutput } from '~/common/outputs'
import { logger } from '~/common/utils/logger'
import { PipelineResult, dlq, ok, redirect } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { InternalPerson, Person } from '~/types'

import { PersonContext } from './person-context'
import { PersonMergeService, mergeMoveLimitDroppedCounter } from './person-merge-service'
import { PersonMergeLimitExceededError } from './person-merge-types'
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

    async processEvent(): Promise<PipelineResult<Person, AsyncOutput>> {
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
            return this.handleMergeError(mergeResult.error, this.context.event)
        }

        if (personFromMerge && needsPersonUpdate) {
            // Try to shortcut if we have the person from identify or alias
            try {
                const [updatedPerson, updateKafkaAck] =
                    await this.propertyService.updatePersonProperties(personFromMerge)
                return ok(updatedPerson, [identifyOrAliasKafkaAck, updateKafkaAck])
            } catch (error) {
                // Shortcut didn't work, swallow the error and try normal retry loop below
                logger.debug('🔁', `failed update after adding distinct IDs, retrying`, { error })
            }
        }

        if (personFromMerge && !needsPersonUpdate) {
            return ok(personFromMerge, [identifyOrAliasKafkaAck])
        }

        // Handle regular property updates
        const [updatedPerson, updateKafkaAck] = await this.propertyService.handleUpdate()
        return ok(updatedPerson, [identifyOrAliasKafkaAck, updateKafkaAck])
    }

    getContext(): PersonContext {
        return this.context
    }

    private handleMergeError(error: unknown, event: PluginEvent): PipelineResult<Person, AsyncOutput> {
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
                    logger.info('Redirecting to async merge output', {
                        output: ASYNC_OUTPUT,
                        team_id: event.team_id,
                        distinct_id: event.distinct_id,
                    })
                    return redirect('Event redirected to async merge topic', ASYNC_OUTPUT)
                case 'LIMIT':
                    logger.warn('Limit exceeded, will be sent to DLQ', {
                        limit: mergeMode.limit,
                        team_id: event.team_id,
                        distinct_id: event.distinct_id,
                    })
                    return dlq('Merge limit exceeded', error)
                case 'SYNC':
                    // Postgres moves are unbounded in SYNC mode, so only the
                    // personhog saga's move limit produces this here. DLQ
                    // rather than drop or throw: the payload stays replayable,
                    // and a throw would only redeliver into the same limit.
                    logger.error('Merge limit exceeded in SYNC mode; routing the event to the DLQ', {
                        team_id: event.team_id,
                        distinct_id: event.distinct_id,
                        event_uuid: event.uuid,
                        mergeMode: mergeMode,
                    })
                    mergeMoveLimitDroppedCounter.labels({ path: 'sync' }).inc()
                    return dlq(
                        'Merge limit exceeded in SYNC mode',
                        error,
                        [],
                        [
                            {
                                type: 'merge_move_limit_exceeded',
                                details: {
                                    distinctId: event.distinct_id,
                                    eventUuid: event.uuid,
                                    // $identify carries the source id as
                                    // $anon_distinct_id, the alias events as
                                    // alias; preferring one blindly would
                                    // mislabel the warning when a stray copy
                                    // of the other is present.
                                    sourcePersonDistinctId: String(
                                        (event.event === '$identify'
                                            ? (event.properties?.['$anon_distinct_id'] ?? event.properties?.['alias'])
                                            : (event.properties?.['alias'] ??
                                              event.properties?.['$anon_distinct_id'])) ?? event.distinct_id
                                    ),
                                    targetPersonDistinctId: event.distinct_id,
                                    eventDropped: false,
                                },
                                pipelineStep: 'person-merge',
                            },
                        ]
                    )
            }
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
