import { captureException, captureMessage } from '@sentry/node'
import { DateTime } from 'luxon'
import { mkdirSync } from 'node:fs'
import path from 'path'

import { defaultConfig } from '../../../../src/config/config'
import { OffsetHighWaterMarker } from '../../../../src/main/ingestion-queues/session-recording/services/offset-high-water-marker'
import { ReplayEventsIngester } from '../../../../src/main/ingestion-queues/session-recording/services/replay-events-ingester'
import { Hub, PluginsServerConfig, TimestampFormat } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { castTimestampOrNow } from '../../../../src/utils/utils'
import { createIncomingRecordingMessage } from './fixtures'

jest.mock('@sentry/node', () => ({
    captureException: jest.fn(),
    captureMessage: jest.fn(),
}))

describe('replayEventsIngester', () => {
    const config: PluginsServerConfig = {
        ...defaultConfig,
        SESSION_RECORDING_LOCAL_DIRECTORY: '.tmp/test-session-recordings',
    }

    let ingester: ReplayEventsIngester

    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(() => {
        jest.useFakeTimers({
            // magic is for evil wizards
            // setInterval in blob consumer doesn't fire
            // if legacyFakeTimers is false
            // 🤷
            legacyFakeTimers: true,
        })
        mkdirSync(path.join(config.SESSION_RECORDING_LOCAL_DIRECTORY, 'session-buffer-files'), { recursive: true })
    })

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()

        ingester = new ReplayEventsIngester(
            config,
            new OffsetHighWaterMarker(hub.redisPool, 'test-session_replay_events_ingester'),
            hub.db
        )
        await ingester.start()
    })

    afterEach(async () => {
        jest.runOnlyPendingTimers()
        await ingester.stop()
        await closeHub()
    })

    it('does not call Sentry when consuming a valid message', async () => {
        await ingester.consume(createIncomingRecordingMessage({}, { timestamp: Date.now() }, { timestamp: Date.now() }))
        expect(captureException).not.toHaveBeenCalled()
        expect(captureMessage).not.toHaveBeenCalled()
    })

    it('reports invalid timestamp to Sentry', async () => {
        const fortyDaysAgo = DateTime.now().minus({ days: 40 })
        const fortyDaysAgoMillis = fortyDaysAgo.toMillis()
        const fortyDaysAgoISO = castTimestampOrNow(fortyDaysAgo, TimestampFormat.ClickHouse)

        await ingester.consume(
            createIncomingRecordingMessage({}, { timestamp: fortyDaysAgoMillis }, { timestamp: fortyDaysAgoMillis })
        )

        expect(captureException).not.toHaveBeenCalled()
        expect(captureMessage).toHaveBeenCalledWith(`Invalid replay record timestamp: ${fortyDaysAgoISO} for event`, {
            extra: {
                replayRecord: {
                    active_milliseconds: 0,
                    click_count: 0,
                    console_error_count: 0,
                    console_log_count: 0,
                    console_warn_count: 0,
                    distinct_id: 'distinct_id',
                    first_timestamp: fortyDaysAgoISO,
                    first_url: undefined,
                    keypress_count: 0,
                    last_timestamp: fortyDaysAgoISO,
                    mouse_activity_count: 0,
                    session_id: 'session_id_1',
                    size: 4103,
                    team_id: 1,
                    uuid: expect.any(String),
                },
                timestamp: fortyDaysAgoISO,
                uuid: expect.any(String),
            },
            tags: { session_id: 'session_id_1', team: 1 },
        })
    })

    it('reports invalid message to Sentry', async () => {
        const rightNow = DateTime.now()
        const rightNowMillis = rightNow.toMillis()
        const rightNowISO = castTimestampOrNow(rightNow, TimestampFormat.ClickHouse)

        await ingester.consume(
            createIncomingRecordingMessage(
                // it is possible to get objects that don't match the type because JavaScript
                { distinct_id: 12345 as unknown as string },
                { timestamp: rightNowMillis },
                { timestamp: rightNowMillis }
            )
        )

        expect(captureException).not.toHaveBeenCalled()
        expect(captureMessage).toHaveBeenCalledWith(`Invalid replay record for session session_id_1`, {
            extra: {
                replayRecord: {
                    active_milliseconds: 0,
                    click_count: 0,
                    console_error_count: 0,
                    console_log_count: 0,
                    console_warn_count: 0,
                    distinct_id: 12345,
                    first_timestamp: rightNowISO,
                    first_url: undefined,
                    keypress_count: 0,
                    last_timestamp: rightNowISO,
                    mouse_activity_count: 0,
                    session_id: 'session_id_1',
                    size: 4103,
                    team_id: 1,
                    uuid: expect.any(String),
                },
                validationErrors: [
                    {
                        instancePath: '/distinct_id',
                        keyword: 'type',
                        message: 'must be string',
                        params: {
                            type: 'string',
                        },
                        schemaPath: '#/definitions/SummarizedSessionRecordingEvent/properties/distinct_id/type',
                    },
                ],
            },
            tags: { session_id: 'session_id_1', team: 1 },
        })
    })
})
