import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { TeamManagerHandle } from '../../utils/team-manager'
import { CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { createCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { newLifecycleBuilder } from '../common/service-registry'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createClientWarningsPipeline } from './pipeline'

export interface ClientWarningsConsumerDeps {
    outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput | AppMetricsOutput>
    /**
     * Shared service owned by the server-level lifecycle — passed in as a
     * handle (no start/stop) so the consumer can't take over its lifecycle.
     */
    teamManager: TeamManagerHandle
    /**
     * Consumer-owned services. Constructed by the caller (so it can inject
     * the right postgres / redis pool) but registered in the consumer's own
     * Lifecycle below — the consumer brings them up on start and tears them
     * down on stop.
     */
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
    eventFilterManager: EventFilterManager
}

export function createClientWarningsConsumer(config: CommonIngestionConsumerConfig, deps: ClientWarningsConsumerDeps) {
    const lifecycle = newLifecycleBuilder()
        .register('eventIngestionRestrictionManager', deps.eventIngestionRestrictionManager)
        .register('eventFilterManager', deps.eventFilterManager)
        .build('consumer')

    return createCommonIngestionConsumer({
        config,
        lifecycle,
        outputs: deps.outputs,
        pipeline: ({ services, outputs, promiseScheduler }) =>
            createClientWarningsPipeline({
                outputs,
                teamManager: deps.teamManager,
                eventIngestionRestrictionManager: services.eventIngestionRestrictionManager,
                eventFilterManager: services.eventFilterManager,
                promiseScheduler,
            }),
    })
}
