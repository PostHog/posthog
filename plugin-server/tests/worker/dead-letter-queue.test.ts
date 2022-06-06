import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

import { Hub, LogLevel } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { UUIDT } from '../../src/utils/utils'
import { generateEventDeadLetterQueueMessage } from '../../src/worker/ingestion/utils'
import { workerTasks } from '../../src/worker/tasks'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../helpers/clickhouse'
import { resetTestDatabase } from '../helpers/sql'

jest.setTimeout(60000) // 60 sec timeout
jest.mock('../../src/utils/status')
jest.mock('../../src/worker/ingestion/utils', () => {
    const { generateEventDeadLetterQueueMessage } = jest.requireActual('../../src/worker/ingestion/utils')
    return {
        generateEventDeadLetterQueueMessage: jest.fn().mockImplementation(generateEventDeadLetterQueueMessage),
    }
})

class MockEventsProcessor {
    public async processEvent() {
        await new Promise<void>((resolve) => resolve())
        throw new Error('database unavailable')
    }
}

jest.mock('../../src/worker/ingestion/process-event', () => {
    return { EventsProcessor: jest.fn(() => new MockEventsProcessor()) }
})

const EVENT_UUID = new UUIDT().toString()

function createEvent(): PluginEvent {
    return {
        distinct_id: 'my_id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        team_id: 2,
        now: new Date().toISOString(),
        event: 'default event',
        properties: { key: 'value' },
        uuid: EVENT_UUID,
    }
}

describe('events dead letter queue', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub({ LOG_LEVEL: LogLevel.Log })
        console.warn = jest.fn() as any
        await resetTestDatabase()
        await resetTestDatabaseClickhouse()
    })

    afterEach(async () => {
        await closeHub()
    })

    test('events get sent to dead letter queue on error', async () => {
        const ingestResponse1 = await workerTasks.runEventPipeline(hub, { event: createEvent() })
        expect(ingestResponse1).toEqual({
            lastStep: 'prepareEventStep',
            error: 'database unavailable',
            args: expect.anything(),
        })
        expect(generateEventDeadLetterQueueMessage).toHaveBeenCalled()

        await delayUntilEventIngested(() => hub.db.fetchDeadLetterQueueEvents(), 1)

        const deadLetterQueueEvents = await hub.db.fetchDeadLetterQueueEvents()

        expect(deadLetterQueueEvents.length).toEqual(1)

        const dlqEvent = deadLetterQueueEvents[0]
        expect(dlqEvent.event).toEqual('default event')
        expect(dlqEvent.ip).toEqual('127.0.0.1')
        expect(dlqEvent.team_id).toEqual(2)
        expect(dlqEvent.team_id).toEqual(2)
        expect(dlqEvent.error_location).toEqual('plugin_server_ingest_event')
        expect(dlqEvent.error).toEqual('ingestEvent failed. Error: database unavailable')
        expect(dlqEvent.properties).toEqual(JSON.stringify({ key: 'value' }))
        expect(dlqEvent.event_uuid).toEqual(EVENT_UUID)
    })
})
