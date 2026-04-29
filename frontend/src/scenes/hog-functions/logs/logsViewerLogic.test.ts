import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { LogEntryLevel } from '~/types'

import { groupLogs, LogEntry, toAbsoluteClickhouseTimestamp } from './logsViewerLogic'

const makeEntry = (instanceId: string, timestamp: string, level: LogEntryLevel = 'INFO'): LogEntry => ({
    instanceId,
    timestamp: dayjs.tz(timestamp, 'UTC'),
    rawTimestamp: timestamp,
    level,
    message: `msg-${instanceId}-${timestamp}`,
})

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

    describe('groupLogs', () => {
        it('groups entries by instanceId', () => {
            const entries = [
                makeEntry('a', '2024-01-15 10:00:00'),
                makeEntry('b', '2024-01-15 10:01:00'),
                makeEntry('a', '2024-01-15 10:02:00'),
            ]

            const groups = groupLogs(entries)

            expect(groups).toHaveLength(2)
            expect(groups.map((g) => g.instanceId).sort()).toEqual(['a', 'b'])
            expect(groups.find((g) => g.instanceId === 'a')?.entries).toHaveLength(2)
            expect(groups.find((g) => g.instanceId === 'b')?.entries).toHaveLength(1)
        })

        it('tracks min and max timestamps per group', () => {
            const entries = [
                makeEntry('a', '2024-01-15 10:00:00'),
                makeEntry('a', '2024-01-15 10:05:00'),
                makeEntry('a', '2024-01-15 10:02:00'),
            ]

            const groups = groupLogs(entries)
            const group = groups[0]

            expect(group.minTimestamp.format('HH:mm:ss')).toBe('10:00:00')
            expect(group.maxTimestamp.format('HH:mm:ss')).toBe('10:05:00')
        })

        it('sorts entries within a group by timestamp ascending', () => {
            const entries = [
                makeEntry('a', '2024-01-15 10:05:00'),
                makeEntry('a', '2024-01-15 10:00:00'),
                makeEntry('a', '2024-01-15 10:02:00'),
            ]

            const groups = groupLogs(entries)
            const timestamps = groups[0].entries.map((e) => e.timestamp.format('HH:mm:ss'))

            expect(timestamps).toEqual(['10:00:00', '10:02:00', '10:05:00'])
        })

        it.each([
            { levels: ['INFO', 'ERROR', 'WARN'] as LogEntryLevel[], expected: 'WARN' },
            { levels: ['DEBUG', 'WARN', 'LOG'] as LogEntryLevel[], expected: 'LOG' },
            { levels: ['INFO', 'INFO', 'INFO'] as LogEntryLevel[], expected: 'INFO' },
        ])('uses log level from most recent entry: $expected', ({ levels, expected }) => {
            const entries = levels.map((level, i) => makeEntry('a', `2024-01-15 10:0${i}:00`, level))
            const groups = groupLogs(entries)
            expect(groups[0].logLevel).toBe(expected)
        })

        it('deduplicates entries with the same instanceId, level, and timestamp', () => {
            const entries = [
                makeEntry('a', '2024-01-15 10:00:00', 'INFO'),
                makeEntry('a', '2024-01-15 10:00:00', 'INFO'),
                makeEntry('a', '2024-01-15 10:01:00', 'INFO'),
            ]

            const groups = groupLogs(entries)

            expect(groups[0].entries).toHaveLength(2)
        })

        it('merges existing and new entries for the same instanceId', () => {
            const existingEntries = [
                makeEntry('a', '2024-01-15 10:00:00'),
                makeEntry('a', '2024-01-15 10:01:00'),
                makeEntry('b', '2024-01-15 10:00:30'),
            ]
            const newEntries = [makeEntry('a', '2024-01-15 09:58:00'), makeEntry('c', '2024-01-15 09:55:00')]

            const merged = groupLogs([...existingEntries, ...newEntries])

            expect(merged).toHaveLength(3)
            expect(merged.find((g) => g.instanceId === 'a')?.entries).toHaveLength(3)
            expect(merged.find((g) => g.instanceId === 'c')?.entries).toHaveLength(1)
        })

        it('returns groups in newest-first order', () => {
            const entries = [
                makeEntry('a', '2024-01-15 10:00:00'),
                makeEntry('b', '2024-01-15 10:01:00'),
                makeEntry('c', '2024-01-15 10:02:00'),
            ]

            const groups = groupLogs(entries)

            expect(groups.map((g) => g.instanceId)).toEqual(['c', 'b', 'a'])
        })
    })
})
