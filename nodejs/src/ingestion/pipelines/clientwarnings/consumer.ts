import { IngestionOutputsComponent } from '~/common/outputs/ingestion-outputs'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { EventIngestionRestrictionManagerComponent } from '~/common/utils/event-ingestion-restrictions'
import { TeamManager } from '~/common/utils/team-manager'
import { EventFilterManagerComponent } from '~/ingestion/common/event-filters'
import { CommonIngestionConsumerConfig, CommonIngestionConsumerScope } from '~/ingestion/common/ingestion-consumer'
import { ProducerName } from '~/ingestion/common/producers'
import { Scope, extend } from '~/ingestion/common/scopes'
import { PromiseSchedulerComponent } from '~/ingestion/common/utils/promise-scheduler'
import { IngestionConsumerConfig, IngestionOutputsConfig } from '~/ingestion/config'
import { RedisPool } from '~/types'

import { createOutputsRegistry } from './outputs/registry'
import { createClientWarningsPipeline } from './pipeline'

export type ClientWarningsConsumerConfig = CommonIngestionConsumerConfig &
    IngestionOutputsConfig &
    Pick<IngestionConsumerConfig, 'DROP_EVENTS_BY_TOKEN_DISTINCT_ID'>

export type ClientWarningsSharedScope = Scope<{
    postgres: PostgresRouter
    redisPool: RedisPool
    teamManager: TeamManager
    producerRegistry: KafkaProducerRegistry<ProducerName>
}>

export function createClientWarningsConsumer(
    config: ClientWarningsConsumerConfig,
    sharedScope: ClientWarningsSharedScope
) {
    const staticDropEventTokens = config.DROP_EVENTS_BY_TOKEN_DISTINCT_ID.split(',').filter((x) => !!x)
    const scope = extend(sharedScope, 'clientwarnings', (container, builder) =>
        builder
            .add('promiseScheduler', new PromiseSchedulerComponent())
            .add(
                'eventIngestionRestrictionManager',
                new EventIngestionRestrictionManagerComponent(container.redisPool, {
                    pipeline: 'clientwarnings',
                    staticDropEventTokens,
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
