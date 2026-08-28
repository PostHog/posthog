import { ASYNC_OUTPUT, AsyncOutput } from '~/common/outputs'
import { logger } from '~/common/utils/logger'
import { PipelineResult, dlq, ok, redirect } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { InternalPerson, Person } from '~/types'

import { PersonContext } from './person-context'
import { PersonMergeService, mergeMoveLimitDroppedCounter } from './person-merge-service'
import { PersonMergeLimitExceededError, PersonMergeUnknownOutcomeError } from './person-merge-types'
import { PersonPropertyService } from './person-property-service'
import { PersonhogFenceTimeoutError } from './personhog-persons-store'

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
                // A fence wait that ran out its full ceiling is not a
                // transient the fallback below can outwait: the ceiling
                // already covers a whole merge, and a second one here would
                // put a single event past the consumer's poll interval.
                if (error instanceof PersonhogFenceTimeoutError) {
                    throw error
                }
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

        if (error instanceof PersonMergeUnknownOutcomeError) {
            // A backend a release ahead of this build. Throwing would restart
            // the pod, and every redelivery reaches the same build until the
            // roll finishes, so the event waits in the DLQ where it stays
            // replayable. Not dropped: the merge may or may not have
            // happened, and only a replay after the roll can tell.
            logger.error('merge backend answered an outcome this build cannot name; routing the event to the DLQ', {
                team_id: this.context.team.id,
                distinct_id: this.context.distinctId,
                event_uuid: event.uuid,
                outcome: error.outcome,
            })
            return dlq('Merge outcome unknown to this build', error)
        }

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
                    // The Postgres backend cannot produce this error in SYNC mode
                    // (its moves are unbounded), but the personhog saga enforces
                    // a move limit in every mode, making this failure class
                    // personhog-new. Temporary while the permanent fix —
                    // saga-side chunked moves — is unbuilt: the event goes to
                    // the DLQ rather than being dropped or failing the batch
                    // into a redelivery loop. The DLQ keeps the payload
                    // replayable once the limit is raised or chunking lands,
                    // where a drop would lose it. The event uuid makes the
                    // event findable, so it travels in the log and warning.
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
                                    // The source property depends on the
                                    // event kind: $identify carries it as
                                    // $anon_distinct_id, the alias events as
                                    // alias — preferring one blindly would
                                    // mislabel the warning when a stray copy
                                    // of the other is present.
                                    sourcePersonDistinctId: String(
                                        (event.event === '$identify'
                                            ? (event.properties?.['$anon_distinct_id'] ?? event.properties?.['alias'])
                                            : (event.properties?.['alias'] ??
                                              event.properties?.['$anon_distinct_id'])) ?? event.distinct_id
                                    ),
                                    targetPersonDistinctId: event.distinct_id,
                                    // In the DLQ, not dropped: the payload is
                                    // replayable once the limit is raised or
                                    // chunked moves land.
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
