import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { LogEntryLevel } from '~/types'

import {
    buildGroupedLogsQuery,
    groupedLogsSliceRows,
    groupLogs,
    LOG_GROUP_MAX_SLICE_ROWS,
    LOG_GROUP_ROWS_PER_GROUP,
    LOG_GROUP_TOTAL_LOGS_LIMIT,
    LogEntry,
    LogEntryParams,
    logsViewerLogic,
    shouldRetryGroupedLogsWithoutSlice,
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

            expect(
                firstPage
                    .replace('OFFSET 0', 'OFFSET 10')
                    .replace(`LIMIT ${10 * LOG_GROUP_ROWS_PER_GROUP}`, `LIMIT ${20 * LOG_GROUP_ROWS_PER_GROUP}`)
            ).toEqual(secondPage)
        })

        it.each([
            { description: 'first page', args: [10, 0], expected: `LIMIT ${10 * LOG_GROUP_ROWS_PER_GROUP}` },
            { description: 'later page', args: [10, 20], expected: `LIMIT ${30 * LOG_GROUP_ROWS_PER_GROUP}` },
        ] as { description: string; args: [number, number]; expected: string }[])(
            'newest-first groups a slice of the newest rows sized for offset + limit groups ($description)',
            ({ args, expected }) => {
                const query = buildGroupedLogsQuery(makeParams({ order: 'DESC' }), ...args)

                expect(query).toContain('FROM (')
                expect(query).toContain(expected)
            }
        )

        it.each([
            { description: 'oldest-first', params: { order: 'ASC' as const }, args: [10, 0] },
            {
                description: 'pages past the slice cap',
                params: {},
                args: [10, LOG_GROUP_MAX_SLICE_ROWS / LOG_GROUP_ROWS_PER_GROUP],
            },
        ] as { description: string; params: Partial<LogEntryParams>; args: [number, number] }[])(
            'uses the full GROUP BY for $description',
            ({ params, args }) => {
                const request = makeParams(params)

                expect(groupedLogsSliceRows(request, ...args)).toBeNull()
                expect(buildGroupedLogsQuery(request, ...args)).not.toContain('FROM (')
            }
        )
    })

    describe('shouldRetryGroupedLogsWithoutSlice', () => {
        const entriesFor = (instanceIds: string[], linesEach: number = 1): LogEntry[] =>
            instanceIds.flatMap((id) =>
                Array.from({ length: linesEach }, (_, i) =>
                    makeEntry(id, `2024-01-15 10:00:${String(i % 60).padStart(2, '0')}`)
                )
            )

        it.each([
            { description: 'a full page of groups', ids: 10, linesEach: 1, expected: false },
            { description: 'a short page', ids: 3, linesEach: 1, expected: true },
            { description: 'an empty page', ids: 0, linesEach: 1, expected: true },
            {
                description: 'a short page that hit the line cap',
                ids: 2,
                linesEach: LOG_GROUP_TOTAL_LOGS_LIMIT / 2,
                expected: false,
            },
        ])('$description -> retry: $expected', ({ ids, linesEach, expected }) => {
            const instanceIds = Array.from({ length: ids }, (_, i) => `instance-${i}`)

            expect(shouldRetryGroupedLogsWithoutSlice(entriesFor(instanceIds, linesEach), 10)).toBe(expected)
        })
    })

    describe('grouped logs loading', () => {
        const rowsFor = (instanceCount: number): any[][] =>
            Array.from({ length: instanceCount }, (_, i) => [`instance-${i}`, '2024-01-15 10:00:00', 'info', 'msg'])

        beforeEach(() => {
            initKeaTests()
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it.each([
            { description: 'a full sliced page is used as is', firstPageInstances: 10, expectedQueries: 1 },
            {
                description: 'a short sliced page is re-run with the full GROUP BY',
                firstPageInstances: 3,
                expectedQueries: 2,
            },
        ])('$description', async ({ firstPageInstances, expectedQueries }) => {
            const querySpy = jest
                .spyOn(api, 'queryHogQL')
                .mockResolvedValueOnce({ results: rowsFor(firstPageInstances) } as any)
                .mockResolvedValue({ results: rowsFor(3) } as any)

            const logic = logsViewerLogic({ sourceType: 'hog_function', sourceId: 'fn-1', disableUrlSync: true })
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadGroupedLogsSuccess'])

            const groupedQueries = querySpy.mock.calls
                .map(([query]) => String(query))
                .filter((query) => query.includes('GROUP BY instance_id'))
            expect(groupedQueries).toHaveLength(expectedQueries)
            expect(groupedQueries[0]).toContain('FROM (')
            if (expectedQueries === 2) {
                expect(groupedQueries[1]).not.toContain('FROM (')
            }
            logic.unmount()
        })
    })

    describe('disableUrlSync', () => {
        beforeEach(() => {
            useMocks({
                post: {
                    '/api/environments/:team_id/query/': () => [200, { results: [] }],
                },
            })
            initKeaTests()
        })

        it('neither writes its filters to the URL nor reads them back from it', async () => {
            // Several viewers can mount on one scene with unprefixed params. A run-scoped viewer that
            // took `search` from the URL would filter its own entries away on someone else's search.
            const logic = logsViewerLogic({ sourceType: 'hog_flow', sourceId: 'flow-1', disableUrlSync: true })
            logic.mount()
            const before = { ...router.values.searchParams }
            await expectLogic(logic, () => {
                logic.actions.setFilters({ search: 'mine' })
            }).toDispatchActions(['setFilters'])
            expect(router.values.searchParams).toEqual(before)

            router.actions.push(router.values.location.pathname, { search: 'theirs' })
            expect(logic.values.filters.search).toBe('mine')
            logic.unmount()
        })

        it('a viewer without the flag still follows the URL', async () => {
            const logic = logsViewerLogic({ sourceType: 'hog_flow', sourceId: 'flow-1' })
            logic.mount()
            await expectLogic(logic, () => {
                logic.actions.setFilters({ search: 'mine' })
            }).toDispatchActions(['setFilters'])
            expect(router.values.searchParams.search).toBe('mine')

            router.actions.push(router.values.location.pathname, { search: 'theirs' })
            expect(logic.values.filters.search).toBe('theirs')
            logic.unmount()
        })
    })
})
