import { PluginEvent } from '@posthog/plugin-scaffold'

import { UUIDT } from '../../../src/utils/utils'
import { parseDate, parseEventTimestamp } from '../../../src/worker/ingestion/timestamps'

describe('parseDate()', () => {
    const timestamps = [
        '2021-10-29',
        '2021-10-29 00:00:00',
        '2021-10-29 00:00:00.000000',
        '2021-10-29T00:00:00.000Z',
        '2021-10-29 00:00:00+00:00',
        '2021-10-29T00:00:00.000-00:00',
        '2021-10-29T00:00:00.000',
        '2021-10-29T00:00:00.000+00:00',
        '2021-W43-5',
        '2021-302',
    ]

    test.each(timestamps)('parses %s', (timestamp) => {
        const parsedTimestamp = parseDate(timestamp)
        expect(parsedTimestamp.year).toBe(2021)
        expect(parsedTimestamp.month).toBe(10)
        expect(parsedTimestamp.day).toBe(29)
        expect(parsedTimestamp.hour).toBe(0)
        expect(parsedTimestamp.minute).toBe(0)
        expect(parsedTimestamp.second).toBe(0)
        expect(parsedTimestamp.millisecond).toBe(0)
    })
})

describe('parseEventTimestamp()', () => {
    beforeEach(() => {
        jest.useFakeTimers().setSystemTime(new Date('2020-08-12T01:02:00.000Z'))
    })
    afterEach(() => {
        jest.useRealTimers()
    })

    it('captures sent_at to adjusts timestamp', () => {
        const event = {
            timestamp: '2021-10-30T03:02:00.000Z',
            sent_at: '2021-10-30T03:12:00.000Z',
            now: '2021-10-29T01:44:00.000Z',
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls.length).toEqual(0)

        expect(timestamp.toISO()).toEqual('2021-10-29T01:34:00.000Z')
    })

    it('ignores and reports invalid sent_at', () => {
        const event = {
            timestamp: '2021-10-31T00:44:00.000Z',
            sent_at: 'invalid',
            now: '2021-10-30T01:44:00.000Z',
            uuid: new UUIDT(),
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls).toEqual([
            [
                'ignored_invalid_timestamp',
                {
                    field: 'sent_at',
                    reason: 'the input "invalid" can\'t be parsed as ISO 8601',
                    value: 'invalid',
                    eventUuid: event.uuid,
                },
            ],
        ])

        expect(timestamp.toISO()).toEqual('2021-10-31T00:44:00.000Z')
    })

    it('captures sent_at with timezone info', () => {
        const event = {
            timestamp: '2021-10-30T03:02:00.000+04:00',
            sent_at: '2021-10-30T03:12:00.000+04:00',
            now: '2021-10-29T01:44:00.000Z',
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls.length).toEqual(0)

        expect(timestamp.toISO()).toEqual('2021-10-29T01:34:00.000Z')
    })

    it('captures timestamp with no sent_at', () => {
        const event = {
            timestamp: '2021-10-30T03:02:00.000Z',
            now: '2021-10-30T01:44:00.000Z',
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls.length).toEqual(0)

        expect(timestamp.toISO()).toEqual(event.timestamp)
    })

    it('captures with time offset and ignores sent_at', () => {
        const event = {
            offset: 6000, // 6 seconds
            now: '2021-10-29T01:44:00.000Z',
            sent_at: '2021-10-30T03:12:00.000+04:00', // ignored
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls.length).toEqual(0)

        expect(timestamp.toUTC().toISO()).toEqual('2021-10-29T01:43:54.000Z')
    })

    it('captures with time offset', () => {
        const event = {
            offset: 6000, // 6 seconds
            now: '2021-10-29T01:44:00.000Z',
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls.length).toEqual(0)

        expect(timestamp.toUTC().toISO()).toEqual('2021-10-29T01:43:54.000Z')
    })

    it('reports timestamp parsing error and fallbacks to DateTime.utc', () => {
        const event = {
            team_id: 123,
            timestamp: 'notISO',
            now: '2020-01-01T12:00:05.200Z',
            uuid: new UUIDT(),
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls).toEqual([
            [
                'ignored_invalid_timestamp',
                {
                    field: 'timestamp',
                    reason: 'the input "notISO" can\'t be parsed as ISO 8601',
                    value: 'notISO',
                    eventUuid: event.uuid,
                },
            ],
        ])

        expect(timestamp.toUTC().toISO()).toEqual('2020-08-12T01:02:00.000Z')
    })

    it('reports event_timestamp_in_future with sent_at', () => {
        const event = {
            timestamp: '2021-10-29T02:30:00.000Z',
            sent_at: '2021-10-28T01:00:00.000Z',
            now: '2021-10-29T01:00:00.000Z',
            event: 'test event name',
            uuid: '12345678-1234-1234-1234-123456789abc',
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls).toEqual([
            [
                'event_timestamp_in_future',
                {
                    now: '2021-10-29T01:00:00.000Z',
                    offset: '',
                    result: '2021-10-30T02:30:00.000Z',
                    sentAt: '2021-10-28T01:00:00.000Z',
                    timestamp: '2021-10-29T02:30:00.000Z',
                    eventUuid: '12345678-1234-1234-1234-123456789abc',
                    eventName: 'test event name',
                },
            ],
        ])

        expect(timestamp.toISO()).toEqual('2021-10-29T01:00:00.000Z')
    })

    it('reports event_timestamp_in_future with negative offset', () => {
        const event = {
            offset: -82860000,
            now: '2021-10-29T01:00:00.000Z',
            event: 'test event name',
            uuid: '12345678-1234-1234-1234-123456789abc',
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)

        expect(callbackMock.mock.calls).toEqual([
            [
                'event_timestamp_in_future',
                {
                    now: '2021-10-29T01:00:00.000Z',
                    offset: -82860000,
                    result: '2021-10-30T00:01:00.000Z',
                    sentAt: '',
                    timestamp: '',
                    eventUuid: '12345678-1234-1234-1234-123456789abc',
                    eventName: 'test event name',
                },
            ],
        ])

        expect(timestamp.toISO()).toEqual('2021-10-29T01:00:00.000Z')
    })
})
