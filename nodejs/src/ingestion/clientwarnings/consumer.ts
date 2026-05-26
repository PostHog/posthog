import { RedisPool } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
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
     * Infrastructure the consumer needs to construct its own services
     * (`EventIngestionRestrictionManager`, `EventFilterManager`) and register
     * them in its lifecycle.
     */
    postgres: PostgresRouter
    redisPool: RedisPool
    staticDropEventTokens: string[]
}

export function createClientWarningsConsumer(config: CommonIngestionConsumerConfig, deps: ClientWarningsConsumerDeps) {
    const lifecycle = newLifecycleBuilder()
        .register(
            'eventIngestionRestrictionManager',
            new EventIngestionRestrictionManager(deps.redisPool, {
                pipeline: 'clientwarnings',
                staticDropEventTokens: deps.staticDropEventTokens,
            })
        )
        .register('eventFilterManager', new EventFilterManager(deps.postgres))
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
