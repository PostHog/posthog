import { TeamManager } from '../../utils/team-manager'
import { HeatmapsOutput } from '../analytics/outputs'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { newCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createHeatmapsPipeline } from './pipeline'

export interface HeatmapsConsumerDeps {
    outputs: IngestionOutputs<HeatmapsOutput | DlqOutput | IngestionWarningsOutput>
    teamManager: TeamManager
}

export function createHeatmapsConsumer(
    config: CommonIngestionConsumerConfig,
    deps: HeatmapsConsumerDeps
): CommonIngestionConsumer {
    return newCommonIngestionConsumer(config)
        .withService('teamManager', deps.teamManager)
        .setOutputs(deps.outputs)
        .withPipeline(({ outputs, services, promiseScheduler }) =>
            createHeatmapsPipeline({
                outputs,
                teamManager: services.teamManager,
                promiseScheduler,
            })
        )
        .build()
}
