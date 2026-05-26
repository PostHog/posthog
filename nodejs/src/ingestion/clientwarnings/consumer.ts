import { TeamManagerHandle } from '../../utils/team-manager'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { createCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { newLifecycleBuilder } from '../common/service-registry'
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
    // No consumer-owned services yet — the lifecycle is empty. teamManager
    // is owned by the server-level lifecycle and reaches the pipeline via
    // closure on `deps`.
    const lifecycle = newLifecycleBuilder().build('consumer')

    return createCommonIngestionConsumer({
        config,
        lifecycle,
        outputs: deps.outputs,
        pipeline: ({ outputs, promiseScheduler }) =>
            createClientWarningsPipeline({
                outputs,
                teamManager: deps.teamManager,
                promiseScheduler,
            }),
    })
}
