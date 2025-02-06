import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../_tests/helpers/clickhouse'
import { Hub, LogLevel } from '../types'
import { closeHub, createHub } from './hub'
import { captureIngestionWarning } from './ingestion-warnings'

jest.setTimeout(60000) // 60 sec timeout

describe('captureIngestionWarning()', () => {
    let hub: Hub

    beforeEach(async () => {
        hub = await createHub({ LOG_LEVEL: LogLevel.Log })
        await resetTestDatabaseClickhouse()
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    async function fetchWarnings() {
        const { data } = await hub.db.clickhouseQuery('SELECT * FROM ingestion_warnings')
        return data
    }

    it('can read own writes', async () => {
        await captureIngestionWarning(hub.db.kafkaProducer, 2, 'some_type', { foo: 'bar' })

        const warnings = await delayUntilEventIngested(fetchWarnings)
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
