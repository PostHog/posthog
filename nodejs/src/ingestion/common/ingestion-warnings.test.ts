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
            type: 'some_type',
            details: { foo: 'bar' },
        })

        const warnings = await clickhouse.delayUntilEventIngested(
            async () => await clickhouse.query('SELECT * FROM ingestion_warnings')
        )

        expect(warnings).toEqual([
            expect.objectContaining({
                team_id: 2,
                source: 'plugin-server',
                type: 'some_type',
                details: '{"foo":"bar"}',
                timestamp: expect.any(String),
                _timestamp: expect.any(String),
            }),
        ])
    })
})
