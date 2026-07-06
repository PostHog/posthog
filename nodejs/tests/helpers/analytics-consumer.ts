import { Message } from 'node-rdkafka'

import { createHogTransformerService } from '~/cdp/hog-transformations/hog-transformer.service'
import { GroupTypeManagerComponent } from '~/common/groups/group-type-manager'
import { HogTransformerComponent } from '~/common/hog-transformations/hog-transformer-component'
import { createKafkaConsumer } from '~/common/kafka/consumer'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { EventSchemaEnforcementManagerComponent } from '~/common/utils/event-schema-enforcement-manager'
import { ProducerName } from '~/ingestion/common/outputs/producers'
import { Component, newScope } from '~/ingestion/common/scopes'
import { getDefaultIngestionOutputsConfig } from '~/ingestion/config'
import { createAiEventSubpipeline } from '~/ingestion/pipelines/ai'
import { AnalyticsConsumerConfig, AnalyticsOutputs, createAnalyticsConsumer } from '~/ingestion/pipelines/analytics'
import { HealthCheckResult, HealthCheckResultOk } from '~/types'

import { IngestionTestInfra } from './ingestion-e2e'
import { createTestIngestionOutputs, createTestMonitoringOutputs } from './ingestion-outputs'

/** Wraps an already-built value as a scope component with a no-op stop. */
function passthrough<T extends object>(value: T): Component<T> {
    return { start: () => Promise.resolve({ value, stop: () => Promise.resolve() }) }
}

export interface AnalyticsTestConsumer {
    /** Drives the consumer's Kafka batch handler directly, bypassing a real broker. */
    handleKafkaBatch: (messages: Message[]) => Promise<{ backgroundTask?: Promise<unknown> }>
    /** Started scope container — reach the persons/group stores, hog transformer, overflow service here. */
    container: Record<string, object>
    /** The started consumer, e.g. for its `name` and healthcheck. */
    consumer: { name: string; isHealthy: () => Promise<HealthCheckResult> }
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
    kafkaProducer: KafkaProducerWrapper,
    overrides?: Partial<AnalyticsConsumerConfig>
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

    // The producer may be a mock (unit tests read via mockProducerObserver) or a real one
    // (e2e tests read the produced events back through ClickHouse).
    const outputs = createTestIngestionOutputs(kafkaProducer) as unknown as AnalyticsOutputs
    const monitoringOutputs = createTestMonitoringOutputs(kafkaProducer)

    const config: AnalyticsConsumerConfig = {
        ...infra.config,
        ...getDefaultIngestionOutputsConfig(),
        ...overrides,
    }

    const sharedScope = newScope('analytics-test-shared', (b) =>
        b
            .add('postgres', passthrough(infra.postgres))
            .add('redisPool', passthrough(infra.redisPool))
            .add('featureFlagCalledDedupRedisPool', passthrough(infra.redisPool))
            .add('teamManager', passthrough(infra.teamManager))
            .add('cookielessManager', passthrough(infra.cookielessManager))
            .add('producerRegistry', passthrough({} as KafkaProducerRegistry<ProducerName>))
            // Inject the infra's repositories so tests can spy on the same instances the consumer uses.
            .add(
                'repositories',
                passthrough({ personRepository: infra.personRepository, groupRepository: infra.groupRepository })
            )
            .add(
                'hogTransformer',
                new HogTransformerComponent(() =>
                    createHogTransformerService(infra.config, { ...infra, monitoringOutputs })
                )
            )
            .add('outputs', passthrough(outputs))
            .add('eventSchemaEnforcementManager', new EventSchemaEnforcementManagerComponent(infra.postgres))
            .add('groupTypeManager', new GroupTypeManagerComponent(infra.groupRepository, infra.teamManager))
    )

    const consumerScope = createAnalyticsConsumer(config, sharedScope, createAiEventSubpipeline)
    const { consumer, stop, container } = await consumerScope.startForTest()

    if (!capturedHandler) {
        throw new Error('Kafka consumer handler was not captured — did the test jest.mock the kafka consumer module?')
    }
    const handler = capturedHandler

    return {
        handleKafkaBatch: (messages: Message[]) => handler(messages),
        container,
        consumer,
        stop,
    }
}

/**
 * Adapter that fits `createTestWithTeamIngester`'s `IngesterLike` contract (sync build, then
 * `start()`), while driving the analytics consumer through the harness above. `start()` boots
 * the scope and captures the batch handler; `handleKafkaBatch` delegates to it. E2e test files
 * must `jest.mock('~/common/kafka/consumer')` so the harness can capture the handler.
 */
export interface AnalyticsIngesterAdapter {
    start(): Promise<void>
    stop(): Promise<void>
    handleKafkaBatch(messages: Message[]): Promise<{ backgroundTask?: Promise<unknown> }>
}

export function buildAnalyticsTestIngester(
    infra: IngestionTestInfra,
    kafkaProducer: KafkaProducerWrapper,
    overrides?: Partial<AnalyticsConsumerConfig>
): AnalyticsIngesterAdapter {
    let started: AnalyticsTestConsumer | undefined
    return {
        async start() {
            started = await startAnalyticsTestConsumer(infra, kafkaProducer, overrides)
        },
        stop: async () => {
            await started?.stop()
        },
        handleKafkaBatch: (messages: Message[]) => {
            if (!started) {
                throw new Error('buildAnalyticsTestIngester: call start() before handleKafkaBatch()')
            }
            return started.handleKafkaBatch(messages)
        },
    }
}
