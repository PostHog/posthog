import { TeamManager } from '../../utils/team-manager'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { newCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { DlqOutput, EventOutput, IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createAnalyticsPipeline } from './pipeline'

export interface AnalyticsConsumerDeps {
    outputs: IngestionOutputs<EventOutput | DlqOutput | IngestionWarningsOutput>
    teamManager: TeamManager
}

export function createAnalyticsConsumer(
    config: CommonIngestionConsumerConfig,
    deps: AnalyticsConsumerDeps
): CommonIngestionConsumer {
    return newCommonIngestionConsumer(config)
        .withService('teamManager', deps.teamManager)
        .setOutputs(deps.outputs)
        .withPipeline(({ outputs, services, promiseScheduler }) =>
            createAnalyticsPipeline({
                outputs,
                teamManager: services.teamManager,
                promiseScheduler,
                groupId: config.INGESTION_CONSUMER_GROUP_ID,
            })
        )
        .build()
}
