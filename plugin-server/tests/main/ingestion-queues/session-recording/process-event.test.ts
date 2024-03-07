import { DateTime } from 'luxon'

import {
    ConsoleLogEntry,
    createSessionReplayEvent,
    gatherConsoleLogEvents,
    getTimestampsFrom,
    SummarizedSessionRecordingEvent,
} from '../../../../src/main/ingestion-queues/session-recording/process-event'
import { RRWebEvent, TimestampFormat } from '../../../../src/types'
import { castTimestampToClickhouseFormat } from '../../../../src/utils/utils'

describe('session recording process event', () => {
    const sessionReplayEventTestCases: {
        testDescription?: string
        snapshotData: { events_summary: RRWebEvent[] }
        snapshotSource?: string
        expected: Pick<
            SummarizedSessionRecordingEvent,
            | 'click_count'
            | 'keypress_count'
            | 'mouse_activity_count'
            | 'first_url'
            | 'first_timestamp'
            | 'last_timestamp'
            | 'active_milliseconds'
            | 'console_log_count'
            | 'console_warn_count'
            | 'console_error_count'
            | 'size'
            | 'event_count'
            | 'message_count'
            | 'snapshot_source'
        >
    }[] = [
        {
            testDescription: 'click and mouse counts are detected',
            snapshotData: {
                events_summary: [
                    // click
                    { timestamp: 1682449093469, type: 3, data: { source: 2, type: 2 }, windowId: '1' },
                    // dbl click
                    { timestamp: 1682449093469, type: 3, data: { source: 2, type: 4 }, windowId: '1' },
                    // touch end
                    { timestamp: 1682449093469, type: 3, data: { source: 2, type: 9 }, windowId: '1' },
                    // right click
                    { timestamp: 1682449093469, type: 3, data: { source: 2, type: 3 }, windowId: '1' },
                    // touch move - mouse activity but not click activity
                    { timestamp: 1682449093469, type: 3, data: { source: 6 }, windowId: '1' },
                    // mouse move - mouse activity but not click activity
                    { timestamp: 1682449093469, type: 3, data: { source: 1 }, windowId: '1' },
                ],
            },
            expected: {
                click_count: 4,
                keypress_count: 0,
                mouse_activity_count: 6,
                first_url: null,
                first_timestamp: '2023-04-25 18:58:13.469',
                last_timestamp: '2023-04-25 18:58:13.469',
                active_milliseconds: 1, //  one event, but it's active, so active time is 1ms not 0
                console_log_count: 0,
                console_warn_count: 0,
                console_error_count: 0,
                size: 469,
                event_count: 6,
                message_count: 1,
                snapshot_source: 'web',
            },
        },
        {
            testDescription: 'keyboard press is detected',
            snapshotData: {
                // keyboard press
                events_summary: [{ timestamp: 1682449093469, type: 3, data: { source: 5 }, windowId: '1' }],
            },
            expected: {
                click_count: 0,
                keypress_count: 1,
                mouse_activity_count: 0,
                first_url: null,
                first_timestamp: '2023-04-25 18:58:13.469',
                last_timestamp: '2023-04-25 18:58:13.469',
                active_milliseconds: 1, //  one event, but it's active, so active time is 1ms not 0
                console_log_count: 0,
                console_warn_count: 0,
                console_error_count: 0,
                size: 73,
                event_count: 1,
                message_count: 1,
                snapshot_source: 'web',
            },
        },
        {
            testDescription: 'console log entries are counted',
            snapshotData: {
                events_summary: [
                    // keypress
                    { timestamp: 1682449093469, type: 3, data: { source: 5 }, windowId: '1' },
                    {
                        type: 6,
                        data: { plugin: 'rrweb/console@1', payload: { level: 'log' } },
                        timestamp: 1682449093469,
                        windowId: '1',
                    },
                    {
                        type: 6,
                        data: { plugin: 'rrweb/console@1', payload: { level: 'log' } },
                        timestamp: 1682449093469,
                        windowId: '1',
                    },
                    {
                        type: 6,
                        data: { plugin: 'rrweb/console@1', payload: { level: 'warn' } },
                        timestamp: 1682449093469,
                        windowId: '1',
                    },
                    {
                        type: 6,
                        data: { plugin: 'rrweb/console@1', payload: { level: 'warn' } },
                        timestamp: 1682449093469,
                        windowId: '1',
                    },
                    {
                        type: 6,
                        data: { plugin: 'rrweb/console@1', payload: { level: 'warn' } },
                        timestamp: 1682449093469,
                        windowId: '1',
                    },
                    {
                        type: 6,
                        data: { plugin: 'rrweb/console@1', payload: { level: 'error' } },
                        timestamp: 1682449093469,
                        windowId: '1',
                    },
                ],
            },
            expected: {
                click_count: 0,
                keypress_count: 1,
                mouse_activity_count: 0,
                first_url: null,
                first_timestamp: '2023-04-25 18:58:13.469',
                last_timestamp: '2023-04-25 18:58:13.469',
                active_milliseconds: 1, //  one event, but it's active, so active time is 1ms not 0
                console_log_count: 2,
                console_warn_count: 3,
                console_error_count: 1,
                size: 762,
                event_count: 7,
                message_count: 1,
                snapshot_source: 'web',
            },
        },
        {
            testDescription: 'first url detection',
            snapshotData: {
                events_summary: [
                    {
                        timestamp: 1682449093693,
                        type: 5,
                        data: {
                            payload: {
                                // doesn't match because href is nested in payload
                                href: 'http://127.0.0.1:8000/home',
                            },
                        },
                        windowId: '1',
                    },
                    {
                        timestamp: 1682449093469,
                        type: 4,
                        data: {
                            href: 'http://127.0.0.1:8000/second/url',
                        },
                        windowId: '1',
                    },
                ],
            },
            expected: {
                click_count: 0,
                keypress_count: 0,
                mouse_activity_count: 0,
                first_url: 'http://127.0.0.1:8000/second/url',
                first_timestamp: '2023-04-25 18:58:13.469',
                last_timestamp: '2023-04-25 18:58:13.693',
                active_milliseconds: 0, // no data.source, so no activity
                console_log_count: 0,
                console_warn_count: 0,
                console_error_count: 0,
                size: 213,
                event_count: 2,
                message_count: 1,
                snapshot_source: 'web',
            },
        },
        {
            testDescription: 'negative timestamps are not included when picking timestamps',
            snapshotData: {
                events_summary: [
                    // a negative timestamp is ignored when picking timestamps
                    // the event is still included
                    { timestamp: 1682449093000, type: 3, data: { source: 2, type: 2 }, windowId: '1' },
                    { timestamp: 1682449095000, type: 3, data: { source: 2, type: 2 }, windowId: '1' },
                    { timestamp: -922167545571, type: 3, data: { source: 2, type: 2 }, windowId: '1' },
                ],
            },
            expected: {
                click_count: 3,
                keypress_count: 0,
                mouse_activity_count: 3,
                first_url: null,
                first_timestamp: '2023-04-25 18:58:13.000',
                last_timestamp: '2023-04-25 18:58:15.000',
                active_milliseconds: 1,
                console_log_count: 0,
                console_warn_count: 0,
                console_error_count: 0,
                size: 244,
                event_count: 3,
                message_count: 1,
                snapshot_source: 'web',
            },
        },
        {
            testDescription: 'overlapping windows are summed separately for activity',
            snapshotData: {
                events_summary: [
                    // three windows with 1 second, 2 seconds, and 3 seconds of activity
                    // even though they overlap they should be summed separately
                    { timestamp: 1682449093000, type: 3, data: { source: 2, type: 2 }, windowId: '1' },
                    { timestamp: 1682449094000, type: 3, data: { source: 2, type: 2 }, windowId: '1' },
                    { timestamp: 1682449095000, type: 3, data: { source: 2, type: 2 }, windowId: '2' },
                    { timestamp: 1682449097000, type: 3, data: { source: 2, type: 2 }, windowId: '2' },
                    { timestamp: 1682449096000, type: 3, data: { source: 2, type: 2 }, windowId: '3' },
                    { timestamp: 1682449099000, type: 3, data: { source: 2, type: 2 }, windowId: '3' },
                ],
            },
            expected: {
                click_count: 6,
                keypress_count: 0,
                mouse_activity_count: 6,
                first_url: null,
                first_timestamp: '2023-04-25 18:58:13.000',
                last_timestamp: '2023-04-25 18:58:19.000',
                active_milliseconds: 6000, // can sum up the activity across windows
                console_log_count: 0,
                console_warn_count: 0,
                console_error_count: 0,
                size: 487,
                event_count: 6,
                message_count: 1,
                snapshot_source: 'web',
            },
        },
        {
            testDescription: 'mobile snapshot source is stored',
            snapshotData: {
                events_summary: [{ timestamp: 1682449093000, type: 3, data: { source: 2, type: 2 }, windowId: '1' }],
            },
            snapshotSource: 'mobile',
            expected: {
                active_milliseconds: 1,
                click_count: 1,
                console_error_count: 0,
                console_log_count: 0,
                console_warn_count: 0,
                event_count: 1,
                first_timestamp: '2023-04-25 18:58:13.000',
                first_url: null,
                keypress_count: 0,
                last_timestamp: '2023-04-25 18:58:13.000',
                message_count: 1,
                mouse_activity_count: 1,
                size: 82,
                snapshot_source: 'mobile',
            },
        },
    ]

    it.each(sessionReplayEventTestCases)(
        'session replay event generation - $testDescription',
        ({ snapshotData, snapshotSource, expected }) => {
            const data = createSessionReplayEvent(
                'some-id',
                12345,
                '5AzhubH8uMghFHxXq0phfs14JOjH6SA2Ftr1dzXj7U4',
                'abcf-efg',
                snapshotData.events_summary,
                snapshotSource || null
            )

            const expectedEvent: SummarizedSessionRecordingEvent = {
                distinct_id: '5AzhubH8uMghFHxXq0phfs14JOjH6SA2Ftr1dzXj7U4',
                session_id: 'abcf-efg',
                team_id: 12345,
                uuid: 'some-id',
                ...expected,
            }
            expect(data).toEqual(expectedEvent)
        }
    )

    it(`snapshot event with no event summary is ignored`, () => {
        expect(() => {
            createSessionReplayEvent(
                'some-id',
                12345,
                '5AzhubH8uMghFHxXq0phfs14JOjH6SA2Ftr1dzXj7U4',
                'abcf-efg',
                [],
                null
            )
        }).toThrowError()
    })

    it(`snapshot event with no event summary timestamps is ignored`, () => {
        expect(() => {
            createSessionReplayEvent(
                'some-id',
                12345,
                '5AzhubH8uMghFHxXq0phfs14JOjH6SA2Ftr1dzXj7U4',
                'abcf-efg',
                [
                    {
                        type: 5,
                        data: {
                            payload: {
                                // doesn't match because href is nested in payload
                                href: 'http://127.0.0.1:8000/home',
                            },
                        },
                    },
                    {
                        type: 4,
                        data: {
                            href: 'http://127.0.0.1:8000/second/url',
                        },
                    },
                ] as any[],
                null
            )
        }).toThrowError()
    })

    test.each([
        { events: [], expectedTimestamps: [] },
        { events: [{ without: 'timestamp property' } as unknown as RRWebEvent], expectedTimestamps: [] },
        { events: [{ timestamp: undefined } as unknown as RRWebEvent], expectedTimestamps: [] },
        { events: [{ timestamp: null } as unknown as RRWebEvent], expectedTimestamps: [] },
        { events: [{ timestamp: 'what about a string' } as unknown as RRWebEvent], expectedTimestamps: [] },
        // we have seen negative timestamps from clients 🙈
        { events: [{ timestamp: -1 } as unknown as RRWebEvent], expectedTimestamps: [] },
        { events: [{ timestamp: 0 } as unknown as RRWebEvent], expectedTimestamps: [] },
        { events: [{ timestamp: 1 } as unknown as RRWebEvent], expectedTimestamps: ['1970-01-01 00:00:00.001'] },
    ])('timestamps from rrweb events', ({ events, expectedTimestamps }) => {
        expect(getTimestampsFrom(events)).toEqual(expectedTimestamps)
    })

    function consoleMessageFor(payload: any[]) {
        return {
            timestamp: 1682449093469,
            type: 6,
            data: {
                plugin: 'rrweb/console@1',
                payload: {
                    level: 'info',
                    payload: payload,
                },
            },
        }
    }

    test.each([
        {
            payload: ['the message', 'more strings', '', null, false, 0, { blah: 'wat' }],
            expectedMessage: 'the message more strings',
        },
        {
            // lone surrogate pairs are replaced with the "unknown" character
            payload: ['\\\\\\",\\\\\\"emoji_flag\\\\\\":\\\\\\"\ud83c...[truncated]'],
            expectedMessage: '\\\\\\",\\\\\\"emoji_flag\\\\\\":\\\\\\"\ufffd...[truncated]',
        },
        {
            // sometimes the strings are wrapped in quotes...
            payload: ['"test"'],
            expectedMessage: '"test"',
        },
        {
            // let's not accept arbitrary length content
            payload: [new Array(3001).join('a')],
            expectedMessage: new Array(3000).join('a'),
        },
    ])('simple console log processing', ({ payload, expectedMessage }) => {
        const consoleLogEntries = gatherConsoleLogEvents(12345, 'session_id', [
            consoleMessageFor(payload),
            // see https://posthog.sentry.io/issues/4525043303
            // null events always ignored
            null as unknown as RRWebEvent,
        ])
        expect(consoleLogEntries).toEqual([
            {
                team_id: 12345,
                log_level: 'info',
                log_source: 'session_replay',
                log_source_id: 'session_id',
                instance_id: null,
                timestamp: castTimestampToClickhouseFormat(
                    DateTime.fromMillis(1682449093469),
                    TimestampFormat.ClickHouse
                ),
                message: expectedMessage,
            } satisfies ConsoleLogEntry,
        ])
    })
})
