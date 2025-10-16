import { Hub } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { captureIngestionWarning } from '../../../src/worker/ingestion/utils'
import { Clickhouse } from '../../helpers/clickhouse'

jest.setTimeout(60000) // 60 sec timeout

describe('captureIngestionWarning()', () => {
    let hub: Hub
    let clickhouse: Clickhouse

    beforeEach(async () => {
        hub = await createHub({ LOG_LEVEL: 'info' })
        clickhouse = Clickhouse.create()
        await clickhouse.resetTestDatabase()
    })

    afterEach(async () => {
        clickhouse.close()
        await closeHub(hub)
    })

    it('can read own writes', async () => {
        await captureIngestionWarning(hub.db.kafkaProducer, 2, 'some_type', { foo: 'bar' })

        const warnings = await clickhouse.delayUntilEventIngested(
            async () => await clickhouse.query('SELECT * FROM ingestion_warnings')
        )

        expect(warnings).toEqual([
            expect.objectContaining({
                team_id: '2',
                source: 'plugin-server',
                type: 'some_type',
                details: '{"foo":"bar"}',
                timestamp: expect.any(String),
                _timestamp: expect.any(String),
            }),
        ])
    })
})
