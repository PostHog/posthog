import { RedisPool } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { TeamManager } from '../../utils/team-manager'
import { CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { createCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { EventFilterManager } from '../common/event-filters'
import { AppMetricsOutput, DlqOutput, IngestionWarningsOutput } from '../common/outputs'
import { Lifecycle } from '../common/service-registry'
import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { createClientWarningsPipeline } from './pipeline'

export interface ClientWarningsConsumerDeps {
    outputs: IngestionOutputs<IngestionWarningsOutput | DlqOutput | AppMetricsOutput>
    /**
     * Server-level lifecycle exposing the infrastructure the consumer needs
     * — postgres, redis pool, and shared services (`teamManager`). The
     * consumer chains its own services on top via `Lifecycle.chain`; the
     * parent's boot is shared via refcount across all consumers rooted
     * at it.
     */
    sharedLifecycle: Lifecycle<{
        postgres: PostgresRouter
        redisPool: RedisPool
        teamManager: TeamManager
    }>
    staticDropEventTokens: string[]
}

export function createClientWarningsConsumer(config: CommonIngestionConsumerConfig, deps: ClientWarningsConsumerDeps) {
    const lifecycle = deps.sharedLifecycle.chain('clientwarnings', (services, builder) =>
        builder
            .register(
                'eventIngestionRestrictionManager',
                new EventIngestionRestrictionManager(services.redisPool, {
                    pipeline: 'clientwarnings',
                    staticDropEventTokens: deps.staticDropEventTokens,
                })
            )
            .register('eventFilterManager', new EventFilterManager(services.postgres))
    )

    return createCommonIngestionConsumer({
        config,
        lifecycle,
        outputs: deps.outputs,
        pipeline: ({ services, outputs, promiseScheduler }) =>
            createClientWarningsPipeline({
                outputs,
                teamManager: services.teamManager,
                eventIngestionRestrictionManager: services.eventIngestionRestrictionManager,
                eventFilterManager: services.eventFilterManager,
                promiseScheduler,
            }),
    })
}
