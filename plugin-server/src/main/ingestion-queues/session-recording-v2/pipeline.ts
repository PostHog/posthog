import { Message } from 'node-rdkafka'

import { BatchPipeline } from '../../../ingestion/pipelines/batch-pipeline.interface'
import { newBatchPipelineBuilder } from '../../../ingestion/pipelines/builders'
import { PipelineConfig } from '../../../ingestion/pipelines/result-handling-pipeline'
import { EventHeaders } from '../../../types'
import { EventIngestionRestrictionManager } from '../../../utils/event-ingestion-restriction-manager'
import { ParsedMessageData } from './kafka/types'
import { SessionBatchManager } from './sessions/session-batch-manager'
import { SessionBatchRecorder } from './sessions/session-batch-recorder'
import { createApplyDropRestrictionsStep } from './steps/apply-drop-restrictions'
import { createApplyOverflowRestrictionsStep } from './steps/apply-overflow-restrictions'
import { createCollectBatchMetricsStep } from './steps/collect-batch-metrics'
import { createObtainBatchStep } from './steps/obtain-batch'
import { createParseHeadersStep } from './steps/parse-headers'
import { createParseKafkaMessageStep } from './steps/parse-kafka-message'
import { createResolveTeamStep } from './steps/resolve-team'
import { TeamService } from './teams/team-service'
import { TeamForReplay } from './teams/types'

export interface SessionRecordingPipelineConfig extends PipelineConfig {
    restrictionManager: EventIngestionRestrictionManager
    overflowTopic: string
    consumeOverflow: boolean
    teamService: TeamService
    sessionBatchManager: SessionBatchManager
}

export function createSessionRecordingPipeline(config: SessionRecordingPipelineConfig): BatchPipeline<
    { message: Message },
    {
        message: Message
        headers: EventHeaders
        parsedMessage: ParsedMessageData
        team: TeamForReplay
        batchRecorder: SessionBatchRecorder
    },
    { message: Message }
> {
    return (
        newBatchPipelineBuilder<{ message: Message }, { message: Message }>()
            // Step 0: Collect batch metrics (batch-level)
            .pipeBatch(createCollectBatchMetricsStep())

            .messageAware((builder) =>
                builder.sequentially((b) =>
                    b
                        // Step 1: Parse headers
                        .pipe(createParseHeadersStep())

                        // Step 2a: Apply drop restrictions
                        .pipe(createApplyDropRestrictionsStep(config.restrictionManager))

                        // Step 2b: Apply overflow restrictions
                        .pipe(
                            createApplyOverflowRestrictionsStep(
                                config.restrictionManager,
                                config.overflowTopic,
                                config.consumeOverflow
                            )
                        )

                        // Step 3: Parse Kafka message
                        .pipe(createParseKafkaMessageStep())

                        // Step 4: Resolve team
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

            // Step 5: Obtain batch recorder (batch-level within team context)
            .messageAware((builder) =>
                builder.teamAware((b) => b.gather().pipeBatch(createObtainBatchStep(config.sessionBatchManager)))
            )
            .handleResults(config)
            .handleSideEffects(config.promiseScheduler, { await: false })

            .build()
    )
}
