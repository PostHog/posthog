import { RedisPool } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { EventIngestionRestrictionManagerScope } from '../../utils/event-ingestion-restrictions'
import { TeamManager } from '../../utils/team-manager'
import { EventFilterManagerScope } from '../common/event-filters'
import { CommonIngestionConsumerConfig, CommonIngestionConsumerScope } from '../common/ingestion-consumer'
import { ProducerName } from '../common/outputs'
import { Scope } from '../common/service-registry'
import { PromiseSchedulerScope } from '../common/utils/promise-scheduler'
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
            .register('promiseScheduler', new PromiseSchedulerScope())
            .register(
                'eventIngestionRestrictionManager',
                new EventIngestionRestrictionManagerScope(container.redisPool, {
                    pipeline: 'clientwarnings',
                    staticDropEventTokens: container.staticDropEventTokens,
                })
            )
            .register('eventFilterManager', new EventFilterManagerScope(container.postgres))
            .register(
                'outputs',
                new IngestionOutputsScope(() => createOutputsRegistry().build(container.producerRegistry, config))
            )
    )

    return new CommonIngestionConsumerScope('clientwarnings', config, scope, ({ container }) =>
        createClientWarningsPipeline(container)
    )
}
