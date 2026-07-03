import { Message } from 'node-rdkafka'

import { createHogTransformerService } from '~/cdp/hog-transformations/hog-transformer.service'
import { HogTransformerComponent } from '~/common/hog-transformations/hog-transformer-component'
import { createKafkaConsumer } from '~/common/kafka/consumer'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { ProducerName } from '~/ingestion/common/outputs/producers'
import { Component, newScope } from '~/ingestion/common/scopes'
import { getDefaultIngestionOutputsConfig } from '~/ingestion/config'
import { createAiEventSubpipeline } from '~/ingestion/pipelines/ai'
import { AnalyticsConsumerConfig, AnalyticsOutputs, createAnalyticsConsumer } from '~/ingestion/pipelines/analytics'
import { HealthCheckResultOk } from '~/types'

import { IngestionTestInfra } from './ingestion-e2e'
import { createTestIngestionOutputs, createTestMonitoringOutputs } from './ingestion-outputs'

/** Wraps an already-built value as a scope component with a no-op stop. */
function passthrough<T extends object>(value: T): Component<T> {
    return { start: () => Promise.resolve({ value, stop: () => Promise.resolve() }) }
}

export interface AnalyticsTestConsumer {
    /** Drives the consumer's Kafka batch handler directly, bypassing a real broker. */
    handleKafkaBatch: (messages: Message[]) => Promise<{ backgroundTask?: Promise<unknown> }>
    /** Started scope container — reach the persons/group stores and hog transformer here. */
    container: Record<string, object>
    stop: () => Promise<void>
}

/**
 * Starts an analytics consumer against test infra, capturing its Kafka batch handler
 * instead of connecting to a broker. Test files must `jest.mock('~/common/kafka/consumer')`
 * so `createKafkaConsumer` is a jest mock this helper can drive.
 *
 * The returned `handleKafkaBatch` matches the legacy `IngestionConsumer.handleKafkaBatch`
 * shape, so existing test bodies port over with only setup/teardown changes.
 */
export async function startAnalyticsTestConsumer(
    infra: IngestionTestInfra,
    mockProducer: KafkaProducerWrapper,
    overrides?: { topic?: string; groupId?: string }
): Promise<AnalyticsTestConsumer> {
    let capturedHandler: ((messages: Message[]) => Promise<{ backgroundTask?: Promise<unknown> }>) | undefined
    ;(createKafkaConsumer as jest.Mock).mockImplementation(() => ({
        connect: (handler: (messages: Message[]) => Promise<{ backgroundTask?: Promise<unknown> }>) => {
            capturedHandler = handler
            return Promise.resolve()
        },
        disconnect: () => Promise.resolve(),
        isHealthy: () => new HealthCheckResultOk(),
    }))

    const outputs = createTestIngestionOutputs(mockProducer) as unknown as AnalyticsOutputs

    const config: AnalyticsConsumerConfig = {
        ...infra.config,
        ...getDefaultIngestionOutputsConfig(),
        ...(overrides?.topic ? { INGESTION_CONSUMER_CONSUME_TOPIC: overrides.topic } : {}),
        ...(overrides?.groupId ? { INGESTION_CONSUMER_GROUP_ID: overrides.groupId } : {}),
    }

    const sharedScope = newScope('analytics-test-shared', (b) =>
        b
            .add('postgres', passthrough(infra.postgres))
            .add('redisPool', passthrough(infra.redisPool))
            .add('featureFlagCalledDedupRedisPool', passthrough(infra.redisPool))
            .add('teamManager', passthrough(infra.teamManager))
            .add('cookielessManager', passthrough(infra.cookielessManager))
            .add('producerRegistry', passthrough({} as KafkaProducerRegistry<ProducerName>))
            .add(
                'hogTransformer',
                new HogTransformerComponent(() =>
                    createHogTransformerService(infra.config, {
                        ...infra,
                        monitoringOutputs: createTestMonitoringOutputs(mockProducer),
                    })
                )
            )
            .add('outputs', passthrough(outputs))
    )

    const consumerScope = createAnalyticsConsumer(config, sharedScope, createAiEventSubpipeline)
    const { stop, container } = await consumerScope.start()

    if (!capturedHandler) {
        throw new Error('Kafka consumer handler was not captured — did the test jest.mock the kafka consumer module?')
    }
    const handler = capturedHandler

    return {
        handleKafkaBatch: (messages: Message[]) => handler(messages),
        container,
        stop,
    }
}
