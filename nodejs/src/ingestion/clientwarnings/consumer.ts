import { RedisPool } from '../../types'
import { PostgresRouter } from '../../utils/db/postgres'
import { EventIngestionRestrictionManagerComponent } from '../../utils/event-ingestion-restrictions'
import { TeamManager } from '../../utils/team-manager'
import { EventFilterManagerComponent } from '../common/event-filters'
import { CommonIngestionConsumerConfig, CommonIngestionConsumerScope } from '../common/ingestion-consumer'
import { ProducerName } from '../common/outputs'
import { Scope, extend } from '../common/scopes'
import { PromiseSchedulerComponent } from '../common/utils/promise-scheduler'
import { IngestionOutputsConfig } from '../config'
import { IngestionOutputsComponent } from '../outputs/ingestion-outputs'
import { KafkaProducerRegistry } from '../outputs/kafka-producer-registry'
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
    const scope = extend(sharedScope, 'clientwarnings', (container, builder) =>
        builder
            .add('promiseScheduler', new PromiseSchedulerComponent())
            .add(
                'eventIngestionRestrictionManager',
                new EventIngestionRestrictionManagerComponent(container.redisPool, {
                    pipeline: 'clientwarnings',
                    staticDropEventTokens: container.staticDropEventTokens,
                })
            )
            .add('eventFilterManager', new EventFilterManagerComponent(container.postgres))
            .add(
                'outputs',
                new IngestionOutputsComponent(() => createOutputsRegistry().build(container.producerRegistry, config))
            )
    )

    return new CommonIngestionConsumerScope('clientwarnings', config, scope, ({ container }) =>
        createClientWarningsPipeline(container)
    )
}
