import { Message } from 'node-rdkafka'

import { BatchPipeline } from '../../../ingestion/pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from '../../../ingestion/pipelines/builders'
import { PipelineConfig } from '../../../ingestion/pipelines/result-handling-pipeline'
import { KafkaConsumer } from '../../../kafka/consumer'
import { ValueMatcher } from '../../../types'
import { EventIngestionRestrictionManager } from '../../../utils/event-ingestion-restriction-manager'
import { SessionBatchManager } from './sessions/session-batch-manager'
import { createApplyDropRestrictionsStep } from './steps/apply-drop-restrictions'
import { createApplyOverflowRestrictionsStep } from './steps/apply-overflow-restrictions'
import { createCollectBatchMetricsStep } from './steps/collect-batch-metrics'
import { createMaybeFlushBatchStep } from './steps/maybe-flush-batch'
import { createObtainBatchStep } from './steps/obtain-batch'
import { createParseHeadersStep } from './steps/parse-headers'
import { createParseKafkaMessageStep } from './steps/parse-kafka-message'
import { createRecordSessionEventStep } from './steps/record-session-event'
import { createResolveTeamStep } from './steps/resolve-team'
import { createSendHeartbeatStep } from './steps/send-heartbeat'
import { TeamService } from './teams/team-service'

export interface SessionRecordingPipelineConfig extends PipelineConfig {
    restrictionManager: EventIngestionRestrictionManager
    overflowTopic: string
    consumeOverflow: boolean
    teamService: TeamService
    sessionBatchManager: SessionBatchManager
    isDebugLoggingEnabled: ValueMatcher<number>
    kafkaConsumer: KafkaConsumer
}

export function createSessionRecordingPipeline(
    config: SessionRecordingPipelineConfig
): BatchPipeline<{ message: Message }, void, { message: Message }> {
    return (
        newBatchPipelineBuilder<{ message: Message }, { message: Message }>()
            // Step 0: Send heartbeat (batch-level)
            .pipeBatch(createSendHeartbeatStep(config.kafkaConsumer))

            // Step 1: Collect batch metrics (batch-level)
            .pipeBatch(createCollectBatchMetricsStep())

            .messageAware((batch) =>
                batch.sequentially((message) =>
                    message
                        // Step 2: Parse headers
                        .pipe(createParseHeadersStep())

                        // Step 3a: Apply drop restrictions
                        .pipe(createApplyDropRestrictionsStep(config.restrictionManager))

                        // Step 3b: Apply overflow restrictions
                        .pipe(
                            createApplyOverflowRestrictionsStep(
                                config.restrictionManager,
                                config.overflowTopic,
                                config.consumeOverflow
                            )
                        )

                        // Step 4: Parse Kafka message
                        .pipe(createParseKafkaMessageStep())

                        // Step 5: Resolve team
                        .pipe(createResolveTeamStep(config.teamService))
                )
            )
            .handleResults(config)
            .handleSideEffects(config.promiseScheduler, { await: false })
            .gather()
            .filterOk()

            // Add team to context for team-aware pipeline
            .map((element) => ({
                result: element.result,
                context: {
                    ...element.context,
                    team: {
                        id: element.result.value.team.teamId,
                    },
                },
            }))

            // Step 6: Obtain batch recorder (batch-level, no gather needed since we're already gathered from filterOk)
            .pipeBatch(createObtainBatchStep(config.sessionBatchManager))

            // Step 7: Record to batch using batch recorder (sequential, team-aware)
            .messageAware((batch) =>
                batch.teamAware((teamBatch) =>
                    teamBatch.sequentially((message) =>
                        message.pipe(createRecordSessionEventStep(config.isDebugLoggingEnabled))
                    )
                )
            )
            .handleResults(config)
            .handleSideEffects(config.promiseScheduler, { await: false })

            .gather()

            // Step 8: Send heartbeat before flush (batch-level)
            .pipeBatch(createSendHeartbeatStep(config.kafkaConsumer))

            // Step 9: Maybe flush batch (after side effects are handled)
            .pipeBatch(createMaybeFlushBatchStep(config.sessionBatchManager))

            .build()
    )
}
