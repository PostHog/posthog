import { RedisPool } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { EventIngestionRestrictionManagerScope } from '../../utils/event-ingestion-restrictions'
import { TeamManager } from '../../utils/team-manager'
import { CommonIngestionConsumerConfig } from '../common/common-ingestion-consumer'
import { createCommonIngestionConsumer } from '../common/common-ingestion-consumer-builder'
import { EventFilterManager } from '../common/event-filters'
import { ProducerName } from '../common/outputs'
import { Scope } from '../common/service-registry'
import { IngestionOutputsConfig } from '../config'
import { KafkaProducerRegistry } from '../outputs/kafka-producer-registry'
import { IngestionOutputsScope } from '../outputs/scope'
import { createOutputsRegistry } from './outputs/registry'
import { createClientWarningsPipeline } from './pipeline'

export type ClientWarningsConsumerConfig = CommonIngestionConsumerConfig & IngestionOutputsConfig

export type ClientWarningsSharedScope = Scope<{
    postgres: PostgresRouter
    redisPool: RedisPool
    teamManager: TeamManager
    producerRegistry: KafkaProducerRegistry<ProducerName>
    staticDropEventTokens: string[]
}>

export function createClientWarningsConsumer(
    config: ClientWarningsConsumerConfig,
    sharedScope: ClientWarningsSharedScope
) {
    const scope = sharedScope.extend('clientwarnings', (container, builder) =>
        builder
            .register(
                'eventIngestionRestrictionManager',
                new EventIngestionRestrictionManagerScope(container.redisPool, {
                    pipeline: 'clientwarnings',
                    staticDropEventTokens: container.staticDropEventTokens,
                })
            )
            .register('eventFilterManager', new EventFilterManager(container.postgres))
            .register(
                'outputs',
                new IngestionOutputsScope(() => createOutputsRegistry().build(container.producerRegistry, config))
            )
    )

    return createCommonIngestionConsumer({
        config,
        scope,
        pipeline: ({ container, promiseScheduler }) =>
            createClientWarningsPipeline({
                outputs: container.outputs,
                teamManager: container.teamManager,
                eventIngestionRestrictionManager: container.eventIngestionRestrictionManager,
                eventFilterManager: container.eventFilterManager,
                promiseScheduler,
            }),
    })
}
