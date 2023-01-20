import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub } from '../../../../../src/types'
import { createHub } from '../../../../../src/utils/db/hub'
import { UUIDT } from '../../../../../src/utils/utils'
import { EventPipelineRunner } from '../../../../../src/worker/ingestion/event-pipeline/runner'
import { fetchEventsForInterval } from '../../../../../src/worker/vm/upgrades/utils/fetchEventsForInterval'
import { HistoricalExportEvent } from '../../../../../src/worker/vm/upgrades/utils/utils'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../../../helpers/clickhouse'
import { resetTestDatabase } from '../../../../helpers/sql'

jest.mock('../../../../../src/utils/status')

const THIRTY_MINUTES = 1000 * 60 * 30

describe('fetchEventsForInterval()', () => {
    let hub: Hub
    let closeServer: () => Promise<void>

    beforeEach(async () => {
        await resetTestDatabase()
        await resetTestDatabaseClickhouse()
        ;[hub, closeServer] = await createHub()
    })

    afterEach(async () => {
        await closeServer()
    })

    async function ingestEvent(timestamp: string, overrides: Partial<PluginEvent> = {}) {
        const pluginEvent: PluginEvent = {
            event: 'some_event',
            distinct_id: 'some_user',
            site_url: '',
            team_id: 2,
            timestamp: timestamp,
            now: timestamp,
            ip: '',
            uuid: new UUIDT().toString(),
            ...overrides,
        } as any as PluginEvent

        const runner = new EventPipelineRunner(hub, pluginEvent)
        await runner.runEventPipeline(pluginEvent)
    }

    function extract<T extends keyof HistoricalExportEvent>(
        events: Array<HistoricalExportEvent>,
        key: T
    ): Array<HistoricalExportEvent[T]> {
        return events.map((event) => event[key])
    }

    it('fetches events and parses them', async () => {
        await Promise.all([
            ingestEvent('2021-06-01T00:00:00.000Z'), // too old
            ingestEvent('2021-09-01T00:00:00.000Z'), // too new

            ingestEvent('2021-08-01T00:01:00.000Z'),
            ingestEvent('2021-08-01T00:02:00.000Z', { properties: { foo: 'bar' } }),
            ingestEvent('2021-08-01T00:03:00.000Z'),
            ingestEvent('2021-08-01T00:29:59.000Z'),
            ingestEvent('2021-08-01T00:33:00.000Z'),
        ])

        await hub.kafkaProducer.flush()
        await delayUntilEventIngested(() => hub.db.fetchEvents(), 7)

        const events = await fetchEventsForInterval(
            hub.db,
            2,
            new Date('2021-08-01T00:00:00.000Z'),
            0,
            THIRTY_MINUTES,
            2
        )

        expect(events.length).toEqual(2)
        expect(extract(events, 'timestamp')).toEqual(['2021-08-01T00:01:00.000Z', '2021-08-01T00:02:00.000Z'])
        expect(extract(events, 'properties')).toEqual([
            {
                $$historical_export_source_db: 'clickhouse',
                $$historical_export_timestamp: expect.any(String),
                $$is_historical_export_event: true,
            },
            {
                $$historical_export_source_db: 'clickhouse',
                $$historical_export_timestamp: expect.any(String),
                $$is_historical_export_event: true,
                foo: 'bar',
            },
        ])

        const offsetEvents = await fetchEventsForInterval(
            hub.db,
            2,
            new Date('2021-08-01T00:00:00.000Z'),
            2,
            THIRTY_MINUTES,
            2
        )
        expect(offsetEvents.length).toEqual(2)
        expect(extract(offsetEvents, 'timestamp')).toEqual(['2021-08-01T00:03:00.000Z', '2021-08-01T00:29:59.000Z'])

        const offsetEvents2 = await fetchEventsForInterval(
            hub.db,
            2,
            new Date('2021-08-01T00:00:00.000Z'),
            4,
            THIRTY_MINUTES,
            2
        )
        expect(offsetEvents2.length).toEqual(0)
    })
})
