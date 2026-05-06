import { TeamManager } from '../../utils/team-manager'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { newCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createAiPipeline } from './pipeline'

export interface AiConsumerDeps {
    outputs: IngestionOutputs<DlqOutput | IngestionWarningsOutput>
    teamManager: TeamManager
}

export function createAiConsumer(config: CommonIngestionConsumerConfig, deps: AiConsumerDeps): CommonIngestionConsumer {
    return newCommonIngestionConsumer(config)
        .withService('teamManager', deps.teamManager)
        .setOutputs(deps.outputs)
        .withPipeline(({ outputs, services, promiseScheduler }) =>
            createAiPipeline({
                outputs,
                teamManager: services.teamManager,
                promiseScheduler,
            })
        )
        .build()
}
