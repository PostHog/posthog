import { RedisPool } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restrictions'
import { TeamManager } from '../../utils/team-manager'
import { CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { createCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { EventFilterManager } from '../common/event-filters'
import { ProducerName } from '../common/outputs'
import { Lifecycle } from '../common/service-registry'
import { IngestionOutputsConfig } from '../config'
import { KafkaProducerRegistry } from '../outputs/kafka-producer-registry'
import { IngestionOutputsLifecycle } from '../outputs/lifecycle'
import { createOutputsRegistry } from './outputs/registry'
import { createClientWarningsPipeline } from './pipeline'

export type ClientWarningsConsumerConfig = CommonIngestionConsumerConfig & IngestionOutputsConfig

export type ClientWarningsSharedLifecycle = Lifecycle<{
    postgres: PostgresRouter
    redisPool: RedisPool
    teamManager: TeamManager
    producerRegistry: KafkaProducerRegistry<ProducerName>
    staticDropEventTokens: string[]
}>

export function createClientWarningsConsumer(
    config: ClientWarningsConsumerConfig,
    sharedLifecycle: ClientWarningsSharedLifecycle
) {
    const lifecycle = sharedLifecycle.chain('clientwarnings', (services, builder) =>
        builder
            .register(
                'eventIngestionRestrictionManager',
                new EventIngestionRestrictionManager(services.redisPool, {
                    pipeline: 'clientwarnings',
                    staticDropEventTokens: services.staticDropEventTokens,
                })
            )
            .register('eventFilterManager', new EventFilterManager(services.postgres))
            .register(
                'outputs',
                new IngestionOutputsLifecycle(() => createOutputsRegistry().build(services.producerRegistry, config))
            )
    )

    return createCommonIngestionConsumer({
        config,
        lifecycle,
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
