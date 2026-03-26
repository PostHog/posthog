import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { toAbsoluteClickhouseTimestamp } from './logsViewerLogic'

describe('logsViewerLogic', () => {
    describe('toAbsoluteClickhouseTimestamp', () => {
        afterEach(() => jest.restoreAllMocks())

        it('falls back to UTC when teamLogic is not mounted', () => {
            const input = dayjs.tz('2024-01-15 10:30:45.123', 'UTC')
            expect(toAbsoluteClickhouseTimestamp(input)).toBe('2024-01-15 10:30:45.123')
        })

        it.each([
            {
                description: 'normalizes US/Pacific to UTC (fallback: teamLogic not mounted)',
                input: dayjs.tz('2024-01-15 02:30:45.123', 'US/Pacific'),
                expected: '2024-01-15 10:30:45.123',
            },
            {
                description: 'normalizes Europe/Berlin to UTC (fallback: teamLogic not mounted)',
                input: dayjs.tz('2024-01-15 11:30:45.123', 'Europe/Berlin'),
                expected: '2024-01-15 10:30:45.123',
            },
            {
                description: 'normalizes Asia/Tokyo to UTC (fallback: teamLogic not mounted)',
                input: dayjs.tz('2024-01-15 19:30:45.123', 'Asia/Tokyo'),
                expected: '2024-01-15 10:30:45.123',
            },
        ])('$description', ({ input, expected }) => {
            expect(toAbsoluteClickhouseTimestamp(input)).toBe(expected)
        })

        it('formats in team timezone when teamLogic is mounted', () => {
            // The same moment in time: 10:30 UTC = 05:30 America/Bogota (UTC-5)
            const input = dayjs.tz('2024-01-15 10:30:45.123', 'UTC')

            jest.spyOn(teamLogic, 'findMounted').mockReturnValue({
                values: { currentTeam: { timezone: 'America/Bogota' } },
            } as any)

            expect(toAbsoluteClickhouseTimestamp(input)).toBe('2024-01-15 05:30:45.123')
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
