import { mockProducer, mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { Message } from 'node-rdkafka'

import {
    KAFKA_APP_METRICS_2,
    KAFKA_METRICS_CLICKHOUSE,
    KAFKA_METRICS_INGESTION_DLQ,
} from '~/common/config/kafka-topics'
import { APP_METRICS_OUTPUT, AppMetricsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { getDefaultMetricsIngestionConsumerConfig } from './config'
import { DEFAULT_METRICS_RETENTION_DAYS, MetricsIngestionConsumer } from './metrics-ingestion-consumer'
import { METRICS_DLQ_OUTPUT, METRICS_OUTPUT, MetricsDlqOutput, MetricsOutput } from './outputs/outputs'

const createKafkaMessage = (headers: Record<string, string>): Message => {
    // The consumer passes the Avro payload through without decoding it.
    const value = Buffer.from('avro-payload')
    return {
        key: null,
        value,
        size: value.length,
        topic: 'test',
        offset: 0,
        timestamp: Date.now(),
        partition: 1,
        headers: Object.entries(headers).map(([key, headerValue]) => ({ [key]: Buffer.from(headerValue) })),
    }
}

describe('MetricsIngestionConsumer', () => {
    let consumer: MetricsIngestionConsumer
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        hub = await createHub()
        team = (await createTestTeamFixture(hub.postgres)).team

        consumer = new MetricsIngestionConsumer(getDefaultMetricsIngestionConsumerConfig(), {
            teamManager: hub.teamManager,
            quotaLimiting: hub.quotaLimiting,
            outputs: new IngestionOutputs<MetricsOutput | MetricsDlqOutput | AppMetricsOutput>({
                [APP_METRICS_OUTPUT]: new SingleIngestionOutput(
                    APP_METRICS_OUTPUT,
                    KAFKA_APP_METRICS_2,
                    mockProducer,
                    'test'
                ),
                [METRICS_OUTPUT]: new SingleIngestionOutput(
                    METRICS_OUTPUT,
                    KAFKA_METRICS_CLICKHOUSE,
                    mockProducer,
                    'test'
                ),
                [METRICS_DLQ_OUTPUT]: new SingleIngestionOutput(
                    METRICS_DLQ_OUTPUT,
                    KAFKA_METRICS_INGESTION_DLQ,
                    mockProducer,
                    'test'
                ),
            }),
        })
        // NOTE: We don't actually use kafka so we skip instantiation for faster tests
        consumer['kafkaConsumer'] = {
            connect: jest.fn(),
            disconnect: jest.fn(),
            isHealthy: jest.fn().mockReturnValue({ status: 'healthy' }),
        } as any
        await consumer.start()

        jest.spyOn(hub.quotaLimiting, 'isTeamTokenQuotaLimited').mockResolvedValue(false)
    })

    afterEach(async () => {
        await consumer.stop()
        await closeHub(hub)
    })

    it('stamps the default retention-days header on messages produced to ClickHouse', async () => {
        const message = createKafkaMessage({
            token: team.api_token,
            bytes_uncompressed: '100',
            record_count: '1',
        })

        const { backgroundTask } = await consumer.processKafkaBatch([message])
        await backgroundTask

        const produced = mockProducerObserver
            .getProducedMessages()
            .filter((batch) => batch.topic === KAFKA_METRICS_CLICKHOUSE)
        expect(produced).toHaveLength(1)
        expect(produced[0].messages).toHaveLength(1)
        expect(produced[0].messages[0].headers).toEqual(
            expect.objectContaining({
                token: team.api_token,
                team_id: team.id.toString(),
                'retention-days': DEFAULT_METRICS_RETENTION_DAYS.toString(),
            })
        )
    })
})
