import { Message } from 'node-rdkafka'

import { CookielessManagerComponent } from '~/ingestion/common/cookieless/cookieless-manager'
import { KafkaProducerRegistryComponent } from '~/ingestion/common/outputs/producer-registry'
import {
    getDefaultKafkaDownstreamProducerEnvConfig,
    getDefaultKafkaUpstreamProducerEnvConfig,
} from '~/ingestion/common/outputs/producers'
import { Component, newScope } from '~/ingestion/common/scopes'
import { getDefaultIngestionOutputsConfig } from '~/ingestion/config'
import {
    HeatmapsConsumerConfig,
    HeatmapsSharedScope,
    createHeatmapsConsumer,
} from '~/ingestion/pipelines/heatmaps/consumer'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { waitForExpect } from '~/tests/helpers/expectations'
import {
    EventBuilder,
    IngesterLike,
    createKafkaMessages,
    createTestWithTeamIngester,
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

class HeatmapsTestIngester implements IngesterLike {
    private stopScope?: () => Promise<void>

    constructor(private readonly consumerScope: ReturnType<typeof createHeatmapsConsumer>) {}

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

async function fetchHeatmaps(clickhouse: Clickhouse, teamId: number): Promise<any[]> {
    return (await clickhouse.query(`SELECT * FROM heatmaps WHERE team_id = ${teamId}`)) as unknown as any[]
}

describe('Heatmaps consumer E2E', () => {
    const testWithTeamIngester = createTestWithTeamIngester({}, (infra) => {
        const config: HeatmapsConsumerConfig = {
            ...infra.config,
            ...getDefaultIngestionOutputsConfig(),
            INGESTION_CONSUMER_GROUP_ID: 'heatmaps-e2e-test',
            INGESTION_CONSUMER_CONSUME_TOPIC: 'heatmaps-e2e-test',
            INGESTION_PIPELINE: 'heatmaps',
            INGESTION_LANE: null,
            KAFKA_BATCH_START_LOGGING_ENABLED: false,
        }

        // Empty producer env values fall back to the rdkafka defaults (broker
        // `kafka:9092`), which is the same broker the rest of the test suite
        // produces to — so the registry's heatmaps producer reaches ClickHouse.
        const registryConfig = {
            ...getDefaultKafkaUpstreamProducerEnvConfig(),
            ...getDefaultKafkaDownstreamProducerEnvConfig(),
        }
        const sharedScope: HeatmapsSharedScope = newScope('heatmaps-e2e-shared', (b) =>
            b
                .add('postgres', constComponent(infra.postgres))
                .add('redisPool', constComponent(infra.redisPool))
                .add('teamManager', constComponent(infra.teamManager))
                .add('cookielessManager', new CookielessManagerComponent(infra.config, infra.redisPool))
                .add(
                    'producerRegistry',
                    new KafkaProducerRegistryComponent(infra.config.KAFKA_CLIENT_RACK, registryConfig)
                )
        )

        return new HeatmapsTestIngester(createHeatmapsConsumer(config, sharedScope))
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

    testWithTeamIngester('extracts heatmap data to ClickHouse', {}, async ({ ingester, team, token }) => {
        const event = new EventBuilder(team)
            .withEvent('$$heatmap')
            .withProperties({
                $session_id: 'session-1',
                $viewport_width: 1024,
                $viewport_height: 768,
                $current_url: 'http://localhost:3000/',
                $heatmap_data: {
                    'http://localhost:3000/': [{ x: 100, y: 200, target_fixed: false, type: 'click' }],
                },
            })
            .build()

        const { backgroundTask } = await ingester.handleKafkaBatch(createKafkaMessages([event], token))
        await backgroundTask

        await waitForExpect(async () => {
            const heatmaps = await fetchHeatmaps(clickhouse, team.id)
            expect(heatmaps.length).toBe(1)
            expect(heatmaps[0].type).toBe('click')
            expect(heatmaps[0].session_id).toBe('session-1')
        }, 30_000)
    })
})
