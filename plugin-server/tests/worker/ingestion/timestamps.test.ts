import { PluginEvent } from '@posthog/plugin-scaffold'

import { UUIDT } from '../../../src/utils/utils'
import {
    parseDate,
    parseEventTimestamp,
    toStartOfDayInTimezone,
    toYearMonthDayInTimezone,
} from '../../../src/worker/ingestion/timestamps'

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

    it('parses a valid timestamp', () => {
        // Timestamp normalization is now done in Rust capture service
        // This test verifies we correctly parse the already-normalized timestamp
        const event = {
            timestamp: '2021-10-30T03:02:00.000Z',
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls.length).toEqual(0)

        expect(timestamp.toISO()).toEqual('2021-10-30T03:02:00.000Z')
    })

    it('parses timestamp with timezone info', () => {
        const event = {
            timestamp: '2021-10-30T03:02:00.000+04:00',
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls.length).toEqual(0)

        // Should be converted to UTC
        expect(timestamp.toISO()).toEqual('2021-10-29T23:02:00.000Z')
    })

    it('handles out of bounds timestamps', () => {
        // Even though Rust normalizes, we still validate for safety
        // Year 10000 is out of bounds (> 9999) - luxon can't parse it
        const event = {
            timestamp: '10000-01-01T00:00:00.000Z',
            uuid: new UUIDT(),
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls).toEqual([
            [
                'ignored_invalid_timestamp',
                {
                    field: 'timestamp',
                    eventUuid: event.uuid,
                    reason: 'the input "10000-01-01T00:00:00.000Z" can\'t be parsed as ISO 8601',
                    value: '10000-01-01T00:00:00.000Z',
                },
            ],
        ])

        // Falls back to current time
        expect(timestamp.toUTC().toISO()).toEqual('2020-08-12T01:02:00.000Z')
    })

    it('reports timestamp parsing error and fallbacks to DateTime.utc', () => {
        const event = {
            team_id: 123,
            timestamp: 'notISO',
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

    it('returns current time when no timestamp provided', () => {
        const event = {
            uuid: new UUIDT(),
        } as any as PluginEvent

        const callbackMock = jest.fn()
        const timestamp = parseEventTimestamp(event, callbackMock)
        expect(callbackMock.mock.calls.length).toEqual(0)

        // Should return current UTC time
        expect(timestamp.toUTC().toISO()).toEqual('2020-08-12T01:02:00.000Z')
    })
})

describe('toYearMonthDateInTimezone', () => {
    it('returns the correct date in the correct timezone', () => {
        expect(toYearMonthDayInTimezone(new Date('2024-12-13T10:00:00.000Z').getTime(), 'Europe/London')).toEqual({
            year: 2024,
            month: 12,
            day: 13,
        })

        // should be a day ahead due to time zones
        expect(toYearMonthDayInTimezone(new Date('2024-12-13T23:00:00.000Z').getTime(), 'Asia/Tokyo')).toEqual({
            year: 2024,
            month: 12,
            day: 14,
        })

        // should be a day behind due to time zones
        expect(toYearMonthDayInTimezone(new Date('2024-12-13T01:00:00.000Z').getTime(), 'America/Los_Angeles')).toEqual(
            {
                year: 2024,
                month: 12,
                day: 12,
            }
        )

        // should be the same day due to no DST
        expect(toYearMonthDayInTimezone(new Date('2024-12-13T00:00:00.000Z').getTime(), 'Europe/London')).toEqual({
            year: 2024,
            month: 12,
            day: 13,
        })

        // should be a different day due to DST (british summer time)
        expect(toYearMonthDayInTimezone(new Date('2024-06-13T23:00:00.000Z').getTime(), 'Europe/London')).toEqual({
            year: 2024,
            month: 6,
            day: 14,
        })
    })

    it('should throw on invalid timezone', () => {
        expect(() => toYearMonthDayInTimezone(new Date().getTime(), 'Invalid/Timezone')).toThrow('Invalid time zone')
    })
})

describe('toStartOfDayInTimezone', () => {
    it('returns the start of the day in the correct timezone', () => {
        expect(toStartOfDayInTimezone(new Date('2024-12-13T10:00:00.000Z').getTime(), 'Europe/London')).toEqual(
            new Date('2024-12-13T00:00:00Z')
        )

        // would be the following day in Asia/Tokyo, but should be the same day (just earlier) in UTC
        expect(toStartOfDayInTimezone(new Date('2024-12-13T23:00:00.000Z').getTime(), 'Asia/Tokyo')).toEqual(
            new Date('2024-12-13T15:00:00Z')
        )

        // would be the same day in Asia/Tokyo, but back in UTC time it should be the previous day (but later in the day)
        expect(toStartOfDayInTimezone(new Date('2024-12-13T01:00:00.000Z').getTime(), 'Asia/Tokyo')).toEqual(
            new Date('2024-12-12T15:00:00Z')
        )

        // would be the same day in America/Los_Angeles, but earlier in the day when converted to UTC
        expect(toStartOfDayInTimezone(new Date('2024-12-13T23:00:00.000Z').getTime(), 'America/Los_Angeles')).toEqual(
            new Date('2024-12-13T08:00:00Z')
        )

        // would be the previous day in America/Los_Angeles, and when converted to UTC it should stay the previous day
        expect(toStartOfDayInTimezone(new Date('2024-12-13T01:00:00.000Z').getTime(), 'America/Los_Angeles')).toEqual(
            new Date('2024-12-12T08:00:00Z')
        )

        // should be the same day due to no DST
        expect(toStartOfDayInTimezone(new Date('2024-12-13T00:00:00.000Z').getTime(), 'Europe/London')).toEqual(
            new Date('2024-12-13T00:00:00Z')
        )

        // should be a different day due to DST (british summer time)
        expect(toStartOfDayInTimezone(new Date('2024-06-13T00:00:00.000Z').getTime(), 'Europe/London')).toEqual(
            new Date('2024-06-12T23:00:00Z')
        )
    })
})
