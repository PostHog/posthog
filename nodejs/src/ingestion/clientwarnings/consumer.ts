import { TeamManager } from '../../utils/team-manager'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { newCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createClientWarningsPipeline } from './pipeline'

export interface ClientWarningsConsumerDeps {
    outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput>
    teamManager: TeamManager
}

export function createClientWarningsConsumer(
    config: CommonIngestionConsumerConfig,
    deps: ClientWarningsConsumerDeps
): CommonIngestionConsumer {
    return newCommonIngestionConsumer(config)
        .withService('teamManager', deps.teamManager)
        .setOutputs(deps.outputs)
        .withPipeline(({ outputs, services, promiseScheduler }) =>
            createClientWarningsPipeline({
                outputs,
                teamManager: services.teamManager,
                promiseScheduler,
            })
        )
        .build()
}
