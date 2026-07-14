import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { captureIngestionWarning } from '~/ingestion/common/ingestion-warnings'
import { Clickhouse } from '~/tests/helpers/clickhouse'
import { Hub } from '~/types'

jest.setTimeout(60000) // 60 sec timeout

describe('captureIngestionWarning()', () => {
    let hub: Hub
    let clickhouse: Clickhouse
    let kafkaProducer: KafkaProducerWrapper

    beforeEach(async () => {
        hub = await createHub({ LOG_LEVEL: 'info' })
        kafkaProducer = await KafkaProducerWrapper.create(hub.KAFKA_CLIENT_RACK)
        clickhouse = Clickhouse.create()
        await clickhouse.resetTestDatabase()
    })

    afterEach(async () => {
        clickhouse.close()
        await kafkaProducer.disconnect()
        await closeHub(hub)
    })

    it('can read own writes', async () => {
        await captureIngestionWarning(kafkaProducer, 2, {
            // registered as size/error in INGESTION_WARNING_TYPES
            type: 'message_size_too_large',
            // severity inside details must lose to the registry-derived field
            details: {
                foo: 'bar',
                distinctId: 'user-1',
                personId: '019831c9-6491-7000-8000-000000000000',
                severity: 'from-details',
            },
            pipelineStep: 'emit-event',
        })

        const warnings = await clickhouse.delayUntilEventIngested(
            async () => await clickhouse.query('SELECT * FROM ingestion_warnings')
        )

        expect(warnings).toEqual([
            expect.objectContaining({
                team_id: 2,
                source: 'plugin-server',
                type: 'message_size_too_large',
                details: expect.any(String),
                timestamp: expect.any(String),
                _timestamp: expect.any(String),
            }),
        ])

        // v2 derives these columns (DEFAULT expressions) from the exact JSON key names
        // emitted by serializeIngestionWarning — a renamed key silently degrades them
        // to the defaults.
        const v2Warnings = await clickhouse.delayUntilEventIngested(
            async () =>
                await clickhouse.query<{
                    team_id: number
                    type: string
                    category: string
                    severity: string
                    pipeline_step: string
                    distinct_id: string | null
                    person_id: string | null
                }>(
                    'SELECT team_id, type, category, severity, pipeline_step, distinct_id, person_id FROM ingestion_warnings_v2'
                )
        )

        expect(v2Warnings).toEqual([
            {
                team_id: 2,
                type: 'message_size_too_large',
                category: 'size',
                severity: 'error',
                pipeline_step: 'emit-event',
                distinct_id: 'user-1',
                person_id: '019831c9-6491-7000-8000-000000000000',
            },
        ])
    })
})
