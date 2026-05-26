import { TeamManagerHandle } from '../../utils/team-manager'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { createCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createClientWarningsPipeline } from './pipeline'

export interface ClientWarningsConsumerDeps {
    outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput>
    /**
     * Shared service owned by the server-level lifecycle — passed in as a
     * `TeamManagerHandle` (no start/stop) so the consumer can't take over
     * its lifecycle.
     */
    teamManager: TeamManagerHandle
}

export function createClientWarningsConsumer(
    config: CommonIngestionConsumerConfig,
    deps: ClientWarningsConsumerDeps
): CommonIngestionConsumer {
    return createCommonIngestionConsumer({
        config,
        outputs: deps.outputs,
        pipeline: ({ outputs, promiseScheduler }) =>
            createClientWarningsPipeline({
                outputs,
                teamManager: deps.teamManager,
                promiseScheduler,
            }),
    })
}
