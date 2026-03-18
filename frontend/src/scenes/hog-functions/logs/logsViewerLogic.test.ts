import { dayjs } from 'lib/dayjs'

import { toAbsoluteClickhouseTimestamp } from './logsViewerLogic'

describe('logsViewerLogic', () => {
    describe('toAbsoluteClickhouseTimestamp', () => {
        it.each([
            {
                description: 'converts UTC timestamp correctly',
                input: dayjs.tz('2024-01-15 10:30:45.123', 'UTC'),
                expected: '2024-01-15 10:30:45.123',
            },
            {
                description: 'converts US/Pacific timestamp to UTC',
                input: dayjs.tz('2024-01-15 02:30:45.123', 'US/Pacific'),
                expected: '2024-01-15 10:30:45.123',
            },
            {
                description: 'converts Europe/Berlin timestamp to UTC',
                input: dayjs.tz('2024-01-15 11:30:45.123', 'Europe/Berlin'),
                expected: '2024-01-15 10:30:45.123',
            },
            {
                description: 'converts Asia/Tokyo timestamp to UTC',
                input: dayjs.tz('2024-01-15 19:30:45.123', 'Asia/Tokyo'),
                expected: '2024-01-15 10:30:45.123',
            },
        ])('$description', ({ input, expected }) => {
            expect(toAbsoluteClickhouseTimestamp(input)).toBe(expected)
        })

        it('formats timestamp without ISO format', () => {
            const timestamp = dayjs.tz('2024-06-20 14:00:00.000', 'UTC')
            const result = toAbsoluteClickhouseTimestamp(timestamp)

            expect(result).not.toContain('T')
            expect(result).not.toContain('Z')
            expect(result).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$/)
        })
    })
})
