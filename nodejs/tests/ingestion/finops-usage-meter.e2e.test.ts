import { KafkaConsumer, LibrdKafkaError, Message } from 'node-rdkafka'

import { defaultConfig } from '~/common/config/config'
import { KAFKA_CLICKHOUSE_FINOPS_USAGE_METERS } from '~/common/config/kafka-topics'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { FinopsUsageMeter } from '~/common/services/finops-usage-meter'
import { parseJSON } from '~/common/utils/json-parse'
import { waitForExpect } from '~/tests/helpers/expectations'
import { createTestIngestionOutputs } from '~/tests/helpers/ingestion-outputs'
import { TEST_KAFKA_TOPICS, ensureKafkaTopics } from '~/tests/helpers/kafka'

// Distinctive so the produced meter is easy to isolate on the shared topic.
const TEST_TEAM_ID = 9_999_991

// The unit test asserts the payload handed to a mocked output. This one drives the real
// producer against the real Kafka topic and reads the message back, so it catches what the
// mock can't: a produce path that never reaches `clickhouse_finops_usage_meters` (wrong topic
// name / unwired producer) or a serialization the wire mangles. The frozen column set is
// re-asserted here because a drift only matters once it survives a real round-trip.
const WIRE_CONTRACT_COLUMNS = [
    'timestamp',
    'product',
    'team_id',
    'org_id',
    'feature',
    'environment',
    'billable_unit',
    'quantity',
    'system',
    'workload',
    'resource_id',
    'duration_ms',
    'service_name',
    'count',
]

function consumeBatch(consumer: KafkaConsumer, count: number): Promise<Message[]> {
    return new Promise((resolve, reject) => {
        consumer.consume(count, (error: LibrdKafkaError, messages: Message[]) =>
            error ? reject(error) : resolve(messages)
        )
    })
}

describe('FinopsUsageMeter E2E', () => {
    let producer: KafkaProducerWrapper
    let consumer: KafkaConsumer

    beforeAll(async () => {
        await ensureKafkaTopics(TEST_KAFKA_TOPICS)
        producer = await KafkaProducerWrapper.create(undefined)
        consumer = new KafkaConsumer(
            {
                'client.id': 'finops-usage-meter-e2e',
                'group.id': `finops-usage-meter-e2e-${Date.now()}-${Math.random().toString(16).slice(2)}`,
                'metadata.broker.list': (defaultConfig.KAFKA_HOSTS || '').split(',').join(','),
                'enable.auto.commit': false,
                'auto.offset.reset': 'earliest',
            },
            {}
        )
        await new Promise<void>((resolve, reject) => {
            consumer.on('ready', () => resolve())
            consumer.on('event.error', reject)
            consumer.connect()
        })
        consumer.subscribe([KAFKA_CLICKHOUSE_FINOPS_USAGE_METERS])
    })

    afterAll(async () => {
        consumer?.disconnect()
        await producer?.disconnect()
    })

    it('an enabled meter delivers a wire-contract row to the real Kafka topic', async () => {
        const meter = new FinopsUsageMeter(createTestIngestionOutputs(producer), { enabled: true })
        meter.queue({
            product: 'ingestion',
            billableUnit: 'events',
            quantity: 1000,
            teamId: TEST_TEAM_ID,
            system: 'warpstream',
            workload: 'events-ingestion-consumer',
            resourceId: 'events_plugin_ingestion',
        })
        await meter.flush()

        // consume() advances the offset per call, so accumulate across retries while the
        // consumer finishes its initial partition assignment.
        const rows: Record<string, unknown>[] = []
        await waitForExpect(async () => {
            for (const message of await consumeBatch(consumer, 50)) {
                if (!message.value) {
                    continue
                }
                const row = parseJSON(message.value.toString()) as Record<string, unknown>
                if (row.team_id === TEST_TEAM_ID) {
                    rows.push(row)
                }
            }
            expect(rows.length).toBeGreaterThan(0)
        }, 30_000)

        expect(new Set(Object.keys(rows[0]))).toEqual(new Set(WIRE_CONTRACT_COLUMNS))
        expect(rows[0]).toMatchObject({
            product: 'ingestion',
            team_id: TEST_TEAM_ID,
            billable_unit: 'events',
            quantity: 1000,
            system: 'warpstream',
            workload: 'events-ingestion-consumer',
            resource_id: 'events_plugin_ingestion',
            count: 1,
        })
    })
})
