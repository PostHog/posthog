import {
    HogTransformerServiceConfig,
    HogTransformerServiceDeps,
    createHogTransformerService,
} from '@posthog/hog-engine/cdp/hog-transformations/hog-transformer.service'
import { ProducerName } from '@posthog/ingestion-common/outputs/producers'
import { Scope, extend } from '@posthog/ingestion-common/scopes/index'
import { HogTransformerComponent } from '@posthog/node-common/hog-transformations/hog-transformer-component'
import { IngestionOutputsComponent } from '@posthog/node-common/outputs/ingestion-outputs'
import { KafkaProducerRegistry } from '@posthog/node-common/outputs/kafka-producer-registry'
import { PostgresRouter } from '@posthog/node-common/utils/db/postgres'
import { TeamManager } from '@posthog/node-common/utils/team-manager'

import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { IngestionOutputsConfig } from '~/ingestion/config'
import { AiConsumerConfig, createAiConsumer } from '~/ingestion/pipelines/ai'
import { createOutputsRegistry as createAiOutputsRegistry } from '~/ingestion/pipelines/ai/outputs/registry'
import { RedisPool } from '~/types'

export type AiConsumerParentScope = Scope<{
    postgres: PostgresRouter
    redisPool: RedisPool
    teamManager: TeamManager
    cookielessManager: CookielessManager
    producerRegistry: KafkaProducerRegistry<ProducerName>
}>

// The AI consumer cannot construct the CDP-owned hog transformer itself, so the server passes its dependencies
// and this scope builds it with the lane's outputs, which also back the transformer's monitoring.
export function createAiConsumerWithHogTransformer(
    config: AiConsumerConfig & IngestionOutputsConfig & HogTransformerServiceConfig,
    parentScope: AiConsumerParentScope,
    hogTransformerDeps: Omit<HogTransformerServiceDeps, 'monitoringOutputs'>
) {
    const sharedScope = extend(parentScope, 'ai-shared', (container, builder) => {
        const outputs = createAiOutputsRegistry().build(container.producerRegistry, config)
        return builder
            .add(
                'hogTransformer',
                new HogTransformerComponent(() =>
                    createHogTransformerService(config, { ...hogTransformerDeps, monitoringOutputs: outputs })
                )
            )
            .add('outputs', new IngestionOutputsComponent(() => outputs))
    })
    return createAiConsumer(config, sharedScope)
}
