import { Message } from 'node-rdkafka'

import { HogTransformerService, createHogTransformerService } from '~/cdp/hog-transformations/hog-transformer.service'
import { GroupTypeManagerComponent } from '~/common/groups/group-type-manager'
import { HogTransformerComponent } from '~/common/hog-transformations/hog-transformer-component'
import { createKafkaConsumer } from '~/common/kafka/consumer'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { EventSchemaEnforcementManagerComponent } from '~/common/utils/event-schema-enforcement-manager'
import {
    BatchWritingGroupStore,
    BatchWritingGroupStoreComponent,
} from '~/ingestion/common/groups/batch-writing-group-store'
import { ProducerName } from '~/ingestion/common/outputs/producers'
import { MainLaneOverflowRedirectComponent } from '~/ingestion/common/overflow-redirect/main-lane-overflow-redirect'
import { OverflowRedirectService } from '~/ingestion/common/overflow-redirect/overflow-redirect-service'
import {
    BatchWritingPersonsStore,
    BatchWritingPersonsStoreComponent,
} from '~/ingestion/common/persons/batch-writing-person-store'
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
    /** The started consumer, e.g. for its `name` and healthcheck. */
    consumer: { name: string; isHealthy: () => Promise<HealthCheckResult> }
    stop: () => Promise<void>
    /** The consumer's own persons/group stores, for asserting cache and flush behavior. */
    personsStore: BatchWritingPersonsStore
    groupStore: BatchWritingGroupStore
    /** The CDP hog transformer the scope built, for spying on its methods. */
    hogTransformer: HogTransformerService
    /** The overflow redirect service — present only when overflow is enabled for the consumer. */
    overflowRedirectService?: OverflowRedirectService
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

    // Captured by the hogTransformer factory closure below when the scope starts it.
    let hogTransformer: HogTransformerService | undefined

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
                // Capture the built transformer via the factory so tests can spy on it without
                // the scope having to hand back its container.
                new HogTransformerComponent(() => {
                    hogTransformer = createHogTransformerService(infra.config, { ...infra, monitoringOutputs })
                    return hogTransformer
                })
            )
            .add('outputs', passthrough(outputs))
            .add('eventSchemaEnforcementManager', new EventSchemaEnforcementManagerComponent(infra.postgres))
            .add('groupTypeManager', new GroupTypeManagerComponent(infra.groupRepository, infra.teamManager))
    )

    // The persons/group stores and overflow service are built inside the consumer scope, not here.
    // Spy on each component's start() to capture the real instance the scope constructs, then restore
    // the spy — so tests get typed handles to those internals without the production scope returning
    // its container. Instance spies the tests add later (e.g. on `personsStore.flush`) still work.
    const personsStoreStartSpy = jest.spyOn(BatchWritingPersonsStoreComponent.prototype, 'start')
    const groupStoreStartSpy = jest.spyOn(BatchWritingGroupStoreComponent.prototype, 'start')
    const overflowStartSpy = jest.spyOn(MainLaneOverflowRedirectComponent.prototype, 'start')

    const consumerScope = createAnalyticsConsumer(config, sharedScope, createAiEventSubpipeline)
    const { consumer, stop } = await consumerScope.start()

    const personsStoreResult = personsStoreStartSpy.mock.results[0]
    const groupStoreResult = groupStoreStartSpy.mock.results[0]
    const overflowResult = overflowStartSpy.mock.results[0]
    personsStoreStartSpy.mockRestore()
    groupStoreStartSpy.mockRestore()
    overflowStartSpy.mockRestore()

    if (!personsStoreResult || !groupStoreResult) {
        throw new Error('Persons/group store was not constructed by the consumer scope')
    }
    if (!hogTransformer) {
        throw new Error('Hog transformer was not constructed by the consumer scope')
    }
    const personsStore = (await personsStoreResult.value).value
    const groupStore = (await groupStoreResult.value).value
    // Overflow only builds the main-lane component when overflow is enabled for the consumer.
    const overflowRedirectService = overflowResult ? (await overflowResult.value).value : undefined

    if (!capturedHandler) {
        throw new Error('Kafka consumer handler was not captured — did the test jest.mock the kafka consumer module?')
    }
    const handler = capturedHandler

    return {
        handleKafkaBatch: (messages: Message[]) => handler(messages),
        consumer,
        stop,
        personsStore,
        groupStore,
        hogTransformer,
        overflowRedirectService,
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
