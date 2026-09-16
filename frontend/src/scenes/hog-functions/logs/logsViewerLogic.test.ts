import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { LogEntryLevel } from '~/types'

import {
    buildGroupedLogsQuery,
    groupLogs,
    LogEntry,
    LogEntryParams,
    logsViewerLogic,
    toAbsoluteClickhouseTimestamp,
} from './logsViewerLogic'

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

    describe('buildGroupedLogsQuery', () => {
        const makeParams = (overrides: Partial<LogEntryParams> = {}): LogEntryParams => ({
            sourceType: 'hog_flow',
            sourceId: 'batch-job-id',
            levels: ['INFO', 'ERROR'],
            searchGroups: [],
            order: 'DESC',
            ...overrides,
        })

        it.each([
            {
                description: 'paginates the group subquery with the requested limit',
                args: [10, 20],
                expected: 'LIMIT 10',
            },
            { description: 'offsets the group subquery to the requested page', args: [10, 20], expected: 'OFFSET 20' },
            { description: 'defaults to offset 0', args: [10], expected: 'OFFSET 0' },
            {
                description: 'orders groups with a stable instance_id tiebreaker so offset pages do not skip or repeat',
                args: [10],
                expected: 'ORDER BY max(timestamp) DESC, instance_id DESC',
            },
        ] as { description: string; args: [number, number?]; expected: string }[])(
            '$description',
            ({ args, expected }) => {
                expect(buildGroupedLogsQuery(makeParams(), ...args)).toContain(expected)
            }
        )

        it('pages by offset alone, without introducing a timestamp cursor', () => {
            // A batch fires every instance within the same millisecond, so successive pages must differ ONLY by
            // the offset — never by a `timestamp < cursor` boundary, which would hide the remaining groups.
            const firstPage = buildGroupedLogsQuery(makeParams(), 10, 0)
            const secondPage = buildGroupedLogsQuery(makeParams(), 10, 10)

            expect(firstPage.replace('OFFSET 0', 'OFFSET 10')).toEqual(secondPage)
        })
    })

    describe('disableUrlSync', () => {
        const baseProps = { sourceType: 'hog_flow' as const, sourceId: 'flow-1' }

        beforeEach(() => {
            useMocks({
                post: {
                    '/api/environments/:team_id/query/': () => [200, { results: [] }],
                },
            })
            initKeaTests()
        })

        it('keeps a scoped viewer out of the shared URL params', async () => {
            // The params carry no prefix, so a scoped viewer writing them would move the window of
            // every other logs viewer mounted on the same scene.
            const scoped = logsViewerLogic({ ...baseProps, logicKey: 'batch-run-1', disableUrlSync: true })
            scoped.mount()
            const before = { ...router.values.searchParams }

            await expectLogic(scoped, () => {
                scoped.actions.setFilters({ date_from: '-7d' })
            }).toDispatchActions(['setFilters'])

            expect(router.values.searchParams).toEqual(before)
            scoped.unmount()
        })

        it('holds a scoped viewer on its default window when the URL carries another one', () => {
            // The run log hides the date control, so a date_from left behind by another viewer would
            // narrow it to a window predating the run, with nothing on screen to undo it.
            router.actions.push('/pipeline/logs', { date_from: '-1h' })
            const scoped = logsViewerLogic({
                ...baseProps,
                logicKey: 'batch-run-2',
                disableUrlSync: true,
                defaultFilters: { dateFrom: '2026-09-07' },
            })
            scoped.mount()

            router.actions.push('/pipeline/logs', { date_from: '-30m' })

            expect(scoped.values.filters.date_from).toBe('2026-09-07')
            scoped.unmount()
        })

        it('still syncs a viewer that owns the URL', async () => {
            const owning = logsViewerLogic({ ...baseProps, logicKey: 'flat-list' })
            owning.mount()

            await expectLogic(owning, () => {
                owning.actions.setFilters({ date_from: '-7d' })
            }).toDispatchActions(['setFilters'])

            expect(router.values.searchParams.date_from).toBe('-7d')
            owning.unmount()
        })
    })
})
