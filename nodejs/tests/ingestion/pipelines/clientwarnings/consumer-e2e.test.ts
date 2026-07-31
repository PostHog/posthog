import { Message } from 'node-rdkafka'
import { readFileSync } from 'node:fs'
import path from 'node:path'

import { parseJSON } from '~/common/utils/json-parse'
import { KafkaProducerRegistryComponent } from '~/ingestion/common/outputs/producer-registry'
import {
    getDefaultKafkaDownstreamProducerEnvConfig,
    getDefaultKafkaUpstreamProducerEnvConfig,
} from '~/ingestion/common/outputs/producers'
import { Component, newScope } from '~/ingestion/common/scopes'
import { getDefaultIngestionOutputsConfig } from '~/ingestion/config'
import {
    ClientWarningsConsumerConfig,
    ClientWarningsSharedScope,
    createClientWarningsConsumer,
} from '~/ingestion/pipelines/clientwarnings/consumer'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { waitForExpect } from '~/tests/helpers/expectations'
import {
    EventBuilder,
    IngesterLike,
    createKafkaMessages,
    createTestWithTeamIngester,
    fetchIngestionWarnings,
    waitForClickHouseKafkaConsumer,
} from '~/tests/helpers/ingestion-e2e'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from '~/tests/helpers/kafka'
import { resetTestDatabase } from '~/tests/helpers/sql'

type CapturedBatchHandler = (messages: Message[]) => Promise<{ backgroundTask?: Promise<unknown> } | void>

// Captures the per-batch handler that `KafkaConsumerComponent` wires into the
// Kafka consumer at start, so the test can drive batches through the real
// pipeline without a live consumer. Prefixed `mock` so the jest.mock factory
// is allowed to reference it.
let mockCapturedHandler: CapturedBatchHandler | undefined

jest.mock('~/common/kafka/consumer', () => {
    const actual = jest.requireActual('~/common/kafka/consumer')
    const { HealthCheckResultOk } = jest.requireActual('~/types')
    return {
        ...actual,
        createKafkaConsumer: jest.fn(() => ({
            connect: (handler: CapturedBatchHandler) => {
                mockCapturedHandler = handler
                return Promise.resolve()
            },
            disconnect: () => Promise.resolve(),
            isHealthy: () => new HealthCheckResultOk(),
            offsetsStore: () => undefined,
        })),
    }
})

jest.mock('~/common/utils/logger')

function constComponent<T extends object>(value: T): Component<T> {
    return { start: () => Promise.resolve({ value, stop: () => Promise.resolve() }) }
}

// Envelope pin shared with rust/capture/tests/ingestion_warnings_integration.rs,
// which asserts real capture output against it. Replaying the same artifact here
// tests the consumer against what capture actually produces, instead of a literal
// on this side that can drift from the producer without either test noticing.
const CAPTURE_ENVELOPE_FIXTURE = parseJSON(
    readFileSync(
        path.resolve(__dirname, '../../../../../rust/common/ingestion_warnings/capture_envelope.fixture.json'),
        'utf8'
    )
) as { event: string; properties: Record<string, unknown> }

class ClientWarningsTestIngester implements IngesterLike {
    private stopScope?: () => Promise<void>

    constructor(private readonly consumerScope: ReturnType<typeof createClientWarningsConsumer>) {}

    async start(): Promise<void> {
        const { stop } = await this.consumerScope.start()
        this.stopScope = stop
    }

    async stop(): Promise<void> {
        await this.stopScope?.()
    }

    async handleKafkaBatch(messages: Message[]): Promise<{ backgroundTask?: Promise<unknown> }> {
        if (!mockCapturedHandler) {
            throw new Error('Kafka consumer batch handler was not captured — did the consumer start?')
        }
        return (await mockCapturedHandler(messages)) ?? {}
    }
}

describe('ClientWarnings consumer E2E', () => {
    const testWithTeamIngester = createTestWithTeamIngester({}, (infra) => {
        const config: ClientWarningsConsumerConfig = {
            ...infra.config,
            ...getDefaultIngestionOutputsConfig(),
            INGESTION_CONSUMER_GROUP_ID: 'clientwarnings-e2e-test',
            INGESTION_CONSUMER_CONSUME_TOPIC: 'clientwarnings-e2e-test',
            INGESTION_PIPELINE: 'clientwarnings',
            INGESTION_LANE: null,
            KAFKA_BATCH_START_LOGGING_ENABLED: false,
        }

        // Empty producer env values fall back to the rdkafka defaults (broker
        // `kafka:9092`), which is the same broker the rest of the test suite
        // produces to — so the registry's warnings producer reaches ClickHouse.
        const registryConfig = {
            ...getDefaultKafkaUpstreamProducerEnvConfig(),
            ...getDefaultKafkaDownstreamProducerEnvConfig(),
        }
        const sharedScope: ClientWarningsSharedScope = newScope('clientwarnings-e2e-shared', (b) =>
            b
                .add('postgres', constComponent(infra.postgres))
                .add('redisPool', constComponent(infra.redisPool))
                .add('teamManager', constComponent(infra.teamManager))
                .add(
                    'producerRegistry',
                    new KafkaProducerRegistryComponent(infra.config.KAFKA_CLIENT_RACK, registryConfig)
                )
        )

        return new ClientWarningsTestIngester(createClientWarningsConsumer(config, sharedScope))
    })

    let clickhouse: Clickhouse

    beforeAll(async () => {
        clickhouse = Clickhouse.create()
        await ensureKafkaTopics(TEST_KAFKA_TOPICS)
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        await waitForClickHouseKafkaConsumer(clickhouse)
    })

    afterAll(async () => {
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        clickhouse.close()
    })

    testWithTeamIngester('produces a client_ingestion_warning to ClickHouse', {}, async ({ ingester, team, token }) => {
        const event = new EventBuilder(team)
            .withEvent('$$client_ingestion_warning')
            .withProperties({ $$client_ingestion_warning_message: 'test message' })
            .build()

        const { backgroundTask } = await ingester.handleKafkaBatch(createKafkaMessages([event], token))
        await backgroundTask

        await waitForExpect(async () => {
            const warnings = await fetchIngestionWarnings(clickhouse, team.id)
            expect(warnings.length).toBe(1)
            expect(warnings[0].type).toBe('client_ingestion_warning')
            expect(warnings[0].details.message).toBe('test message')
        }, 30_000)
    })

    testWithTeamIngester(
        'resolves a capture envelope to a structured warning',
        {},
        async ({ ingester, team, token }) => {
            const event = new EventBuilder(team)
                .withEvent(CAPTURE_ENVELOPE_FIXTURE.event)
                .withProperties(CAPTURE_ENVELOPE_FIXTURE.properties)
                .build()

            const { backgroundTask } = await ingester.handleKafkaBatch(createKafkaMessages([event], token))
            await backgroundTask

            await waitForExpect(async () => {
                const warnings = await fetchIngestionWarnings(clickhouse, team.id)
                expect(warnings.length).toBe(1)
                // The structured type survives the trust allowlist rather than
                // being downgraded to `client_ingestion_warning`, and `source`
                // reaches the row so warnings stay attributable to capture.
                expect(warnings[0].type).toBe('missing_event_name')
                expect(warnings[0].source).toBe('capture')
                expect(warnings[0].details).toMatchObject({
                    // v2 materializes its pipeline_step column from this key.
                    pipelineStep: 'capture_validation',
                    count: 2,
                    // Stamped from this side's registry, never from the envelope.
                    category: 'event',
                    severity: 'error',
                })
            }, 30_000)
        }
    )
})
