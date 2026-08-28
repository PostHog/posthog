// Serial: asserts an event-loop lag ceiling, so a worker competing for CPU fails it.
import { mockProducer, mockProducerObserver } from '~/tests/helpers/mocks/producer.mock'

import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { KAFKA_APP_METRICS_2, KAFKA_LOGS_CLICKHOUSE, KAFKA_LOGS_INGESTION_DLQ } from '~/common/config/kafka-topics'
import { APP_METRICS_OUTPUT, AppMetricsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { SingleIngestionOutput } from '~/common/outputs/single-ingestion-output'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { createTestTeamFixture } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { LogRecord, encodeLogRecords } from './log-record-avro'
import { LogsIngestionConsumer } from './logs-ingestion-consumer'
import { LOGS_DLQ_OUTPUT, LOGS_OUTPUT, LogsDlqOutput, LogsOutput } from './outputs/outputs'

jest.setTimeout(30000)

let offsetIncrementer = 0

const createKafkaMessages = async (bodies: string[], headers: Record<string, string>): Promise<Message[]> => {
    const avro = require('avsc')
    const logRecordType = avro.Type.forSchema({
        type: 'record',
        name: 'LogRecord',
        fields: [
            { name: 'uuid', type: ['null', 'string'] },
            { name: 'trace_id', type: ['null', 'bytes'] },
            { name: 'span_id', type: ['null', 'bytes'] },
            { name: 'trace_flags', type: ['null', 'int'] },
            { name: 'timestamp', type: ['null', 'long'] },
            { name: 'observed_timestamp', type: ['null', 'long'] },
            { name: 'body', type: ['null', 'string'] },
            { name: 'severity_text', type: ['null', 'string'] },
            { name: 'severity_number', type: ['null', 'int'] },
            { name: 'service_name', type: ['null', 'string'] },
            { name: 'resource_attributes', type: ['null', { type: 'map', values: 'string' }] },
            { name: 'instrumentation_scope', type: ['null', 'string'] },
            { name: 'event_name', type: ['null', 'string'] },
            { name: 'attributes', type: ['null', { type: 'map', values: 'string' }] },
        ],
    })

    return await Promise.all(
        bodies.map(async (body) => {
            const record: LogRecord = {
                uuid: `test-uuid-${offsetIncrementer}`,
                trace_id: null,
                span_id: null,
                trace_flags: null,
                timestamp: DateTime.now().toMillis() * 1000,
                observed_timestamp: DateTime.now().toMillis() * 1000,
                body,
                severity_text: 'info',
                severity_number: 9,
                service_name: 'test-service',
                resource_attributes: null,
                instrumentation_scope: null,
                event_name: null,
                attributes: null,
            }
            const value = await encodeLogRecords(logRecordType, 'zstandard', [record])
            return {
                key: null,
                value,
                size: value.length,
                topic: 'test',
                offset: offsetIncrementer++,
                timestamp: DateTime.now().toMillis(),
                partition: 1,
                headers: Object.entries(headers).map(([key, headerValue]) => ({
                    [key]: Buffer.from(headerValue),
                })),
            }
        })
    )
}

describe('LogsIngestionConsumer thread relief', () => {
    let consumer: LogsIngestionConsumer
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        offsetIncrementer = 0
        hub = await createHub()
        team = (await createTestTeamFixture(hub.postgres)).team

        // PII scrub and JSON parse make processLogMessageBuffer do real CPU work per message.
        // Without them it short-circuits and never decodes the buffer.
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_team SET logs_settings = $1 WHERE id = $2`,
            [JSON.stringify({ pii_scrub_logs: true, json_parse_logs: true }), team.id],
            'updateTeamLogsForThreadRelief'
        )
        hub.teamManager['lazyLoader'].markForRefresh(String(team.id))

        consumer = new LogsIngestionConsumer(hub, {
            ...hub,
            outputs: new IngestionOutputs<AppMetricsOutput | LogsOutput | LogsDlqOutput>({
                [APP_METRICS_OUTPUT]: new SingleIngestionOutput(
                    APP_METRICS_OUTPUT,
                    KAFKA_APP_METRICS_2,
                    mockProducer,
                    'test'
                ),
                [LOGS_OUTPUT]: new SingleIngestionOutput(LOGS_OUTPUT, KAFKA_LOGS_CLICKHOUSE, mockProducer, 'test'),
                [LOGS_DLQ_OUTPUT]: new SingleIngestionOutput(
                    LOGS_DLQ_OUTPUT,
                    KAFKA_LOGS_INGESTION_DLQ,
                    mockProducer,
                    'test'
                ),
            }),
        })
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

    it('should process large batches without blocking the main thread', async () => {
        const body = JSON.stringify({
            user_id: 'usr_abc123',
            email: 'jane.doe@example.com',
            nested: { a: 1, b: 'two', c: [1, 2, 3, 4, 5] },
            message: 'A long log message ' + 'x'.repeat(500),
        })

        const numberToTest = 2000
        const messages = await createKafkaMessages(
            Array.from({ length: numberToTest }, () => body),
            {
                token: team.api_token,
            }
        )

        let lastCheck = Date.now()
        let longestDelay = 0
        const interval = setInterval(() => {
            longestDelay = Math.max(longestDelay, Date.now() - lastCheck)
            lastCheck = Date.now()
        }, 0)

        try {
            await (
                await consumer.processKafkaBatch(messages)
            ).backgroundTask
        } finally {
            clearInterval(interval)
        }

        // Counted rather than decoded: the logs output carries AVRO, not JSON.
        const produced = mockProducerObserver
            .getProducedMessages()
            .filter((batch) => batch.topic === KAFKA_LOGS_CLICKHOUSE)
            .flatMap((batch) => batch.messages)
        expect(produced).toHaveLength(numberToTest)
        expect(longestDelay).toBeLessThan(120)
    })
})
