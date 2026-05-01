import { dayjs } from 'lib/dayjs'

import { WindowDirection, WindowSize, computeDateRange, parseTimestampInput } from './jumpToTimestampUtils'

describe('jumpToTimestamp', () => {
    describe('parseTimestampInput', () => {
        it.each([
            ['unix seconds (9 digits)', '946684800', dayjs(946684800 * 1000)],
            ['unix seconds (10 digits)', '1705312200', dayjs(1705312200 * 1000)],
            ['unix milliseconds (13 digits)', '1705312200000', dayjs(1705312200000)],
            ['unix float seconds', '1705312200.123', dayjs(1705312200123)],
            ['ISO 8601 with Z', '2024-01-15T10:30:00Z', dayjs('2024-01-15T10:30:00Z')],
            ['ISO 8601 with offset', '2024-01-15T10:30:00+05:00', dayjs('2024-01-15T10:30:00+05:00')],
            ['date only', '2024-01-15', dayjs('2024-01-15')],
            ['datetime with space', '2024-01-15 10:30:00', dayjs('2024-01-15 10:30:00')],
            ['US locale MM/DD/YYYY', '01/15/2024', dayjs('01/15/2024', 'MM/DD/YYYY', true)],
            ['compact YYYYMMDD', '20240115', dayjs('20240115', 'YYYYMMDD', true)],
        ])('parses %s (%s)', (_label, input, expected) => {
            const result = parseTimestampInput(input)
            expect(result).not.toBeNull()
            expect(result!.valueOf()).toBeCloseTo(expected.valueOf(), -2)
        })

        it.each([
            ['empty string', ''],
            ['whitespace only', '   '],
            ['not a date', 'not-a-date'],
            ['random text', 'hello world'],
            ['too short number', '123'],
            ['year 1999 (below 2000 boundary)', '1999-12-31'],
        ])('returns null for invalid input: %s (%s)', (_label, input) => {
            expect(parseTimestampInput(input)).toBeNull()
        })

        it('accepts dates at the year 2000 boundary', () => {
            const result = parseTimestampInput('2000-01-01')
            expect(result).not.toBeNull()
            expect(result!.year()).toBe(2000)
        })

        it('returns null for dates too far in the future', () => {
            const farFuture = dayjs().add(2, 'year').format('YYYY-MM-DD')
            expect(parseTimestampInput(farFuture)).toBeNull()
        })
    })

    describe('computeDateRange', () => {
        const ts = dayjs.utc('2024-01-15T12:00:00')

        it.each<[WindowDirection, WindowSize, string, string]>([
            ['before', '5m', '2024-01-15T11:55:00Z', '2024-01-15T12:00:00Z'],
            ['before', '10m', '2024-01-15T11:50:00Z', '2024-01-15T12:00:00Z'],
            ['before', '1h', '2024-01-15T11:00:00Z', '2024-01-15T12:00:00Z'],
            ['around', '5m', '2024-01-15T11:57:30Z', '2024-01-15T12:02:30Z'],
            ['around', '10m', '2024-01-15T11:55:00Z', '2024-01-15T12:05:00Z'],
            ['around', '1h', '2024-01-15T11:30:00Z', '2024-01-15T12:30:00Z'],
            ['after', '5m', '2024-01-15T12:00:00Z', '2024-01-15T12:05:00Z'],
            ['after', '10m', '2024-01-15T12:00:00Z', '2024-01-15T12:10:00Z'],
            ['after', '1h', '2024-01-15T12:00:00Z', '2024-01-15T13:00:00Z'],
        ])('direction=%s window=%s → %s to %s', (direction, windowSize, expectedFrom, expectedTo) => {
            const result = computeDateRange(ts, windowSize, direction)
            expect(result.date_from).toBe(expectedFrom)
            expect(result.date_to).toBe(expectedTo)
        })

        it('converts timezone-aware timestamps to UTC output', () => {
            // 10:30 at +05:00 = 05:30 UTC
            const ts2 = dayjs('2024-01-15T10:30:00+05:00')
            const result = computeDateRange(ts2, '5m', 'around')
            expect(result.date_from).toBe('2024-01-15T05:27:30Z')
            expect(result.date_to).toBe('2024-01-15T05:32:30Z')
        })
    })
})
