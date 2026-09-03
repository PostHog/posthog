import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    buildSearchClause,
    hogInvocationsLogic,
    isRerunnableHogFunctionType,
    parentClauseFor,
} from './hogInvocationsLogic'

describe('hogInvocationsLogic', () => {
    describe('buildSearchClause', () => {
        const props = { id: 'flow-1', functionKind: 'hog_flow' as const }

        it('returns an empty clause when no search is set', () => {
            // An empty clause when a search IS set (covered below) would silently show every run — the
            // failure mode worth locking.
            expect(buildSearchClause(props, { date_from: '-24h' }).raw).toBe('')
        })

        it('matches the typed term as an exact id OR a log-message substring', () => {
            // One typed term goes into every arm: it's compared for equality against each id column (paste
            // an id to find that run) and, via a log_entries subquery, as a substring of the message (type
            // words to find a run that logged them). So the same term appears in all arms below.
            const clause = buildSearchClause(props, { date_from: '-24h', search: 'run-42' }).raw
            expect(clause).toContain("invocation_id = 'run-42'")
            expect(clause).toContain("event_uuid = 'run-42'")
            expect(clause).toContain("distinct_id = 'run-42'")
            expect(clause).toContain("person_id = 'run-42'")
            expect(clause).toContain('FROM log_entries')
            expect(clause).toContain("message ILIKE concat('%', 'run-42', '%')")
            // No level narrowing for a manual search — it matches any level.
            expect(clause).not.toContain('lower(level)')
        })

        it('narrows the message match to log_levels when a drill-down sets them', () => {
            // Drill-downs carry levels so "Bounced" (WARN/ERROR) does not also match the INFO
            // "Email sent to bounce@…" log.
            const clause = buildSearchClause(props, {
                date_from: '-24h',
                search: 'bounce',
                log_levels: ['WARN', 'ERROR'],
            }).raw
            expect(clause).toContain("message ILIKE concat('%', 'bounce', '%')")
            expect(clause).toContain("lower(level) IN ('warn','error')")
        })

        it('escapes ILIKE wildcards in the message arm but not the id arms', () => {
            // Typing "a%b" must match that literal text in messages, not "a<anything>b". The % is
            // backslash-escaped only for the ILIKE arm (then doubled by escapeHogQLString for the SQL
            // literal); the exact-id arms keep the raw term.
            const clause = buildSearchClause(props, { date_from: '-24h', search: 'a%b' }).raw
            expect(clause).toContain("invocation_id = 'a%b'")
            expect(clause).toContain("message ILIKE concat('%', 'a\\\\%b', '%')")
        })
    })

    describe('isRerunnableHogFunctionType', () => {
        // Drives whether the invocations UI offers re-run. Only types a cyclotron worker
        // executes are rerunnable; classifying a source_webhook (or any other type) as
        // rerunnable would surface a button that enqueues an invocation nothing can drain.
        it.each(['destination', 'internal_destination'] as const)('is true for rerunnable type %s', (type) => {
            expect(isRerunnableHogFunctionType(type)).toBe(true)
        })

        it.each(['source_webhook', 'transformation', 'site_app', 'site_destination', 'source'] as const)(
            'is false for non-rerunnable type %s',
            (type) => {
                expect(isRerunnableHogFunctionType(type)).toBe(false)
            }
        )

        it('is false when the type is unknown', () => {
            expect(isRerunnableHogFunctionType(undefined)).toBe(false)
            expect(isRerunnableHogFunctionType(null)).toBe(false)
        })
    })

    describe('parentClauseFor', () => {
        const base = { id: 'flow-1', functionKind: 'hog_flow' as const }

        it('returns an empty clause when no parent run is scoped', () => {
            // Unscoped is the flat list. A non-empty clause here would wrongly filter the whole workflow's runs.
            expect(parentClauseFor(base).raw).toBe('')
        })

        it('scopes to the batch job id when parentRunId is set', () => {
            // The batch view depends on this: without it a job's table shows every run for the workflow,
            // not just that broadcast's. The id goes in as an escaped HogQL string literal.
            expect(parentClauseFor({ ...base, parentRunId: 'job-1' }).raw).toBe("AND parent_run_id = 'job-1'")
        })
    })

    describe('parent-run scope isolation', () => {
        beforeEach(() => {
            useMocks({
                post: {
                    '/api/environments/:team_id/query/': () => [200, { results: [] }],
                },
            })
            initKeaTests()
        })

        it('does not write a scoped table filters to the shared URL', async () => {
            // Several per-job tables can mount on one scene; if a scoped one wrote inv_* params it would
            // clobber the flat list and its siblings. The parentRunId guard in actionToUrl prevents that.
            const scoped = hogInvocationsLogic({ id: 'flow-1', functionKind: 'hog_flow', parentRunId: 'job-1' })
            scoped.mount()
            const before = { ...router.values.searchParams }
            await expectLogic(scoped, () => {
                scoped.actions.setFilters({ date_from: '-7d' })
            }).toDispatchActions(['setFilters'])
            expect(router.values.searchParams).toEqual(before)
            scoped.unmount()
        })

        it('the flat list still writes its filters to the URL', async () => {
            const flat = hogInvocationsLogic({ id: 'flow-1', functionKind: 'hog_flow' })
            flat.mount()
            await expectLogic(flat, () => {
                flat.actions.setFilters({ date_from: '-7d' })
            }).toDispatchActions(['setFilters'])
            expect(router.values.searchParams.inv_date_from).toBe('-7d')
            flat.unmount()
        })

        it('anchors the initial window to defaultDateFrom for a scoped table', () => {
            // A broadcast older than 24h would show no runs if the scoped table used the default -24h window.
            const scoped = hogInvocationsLogic({
                id: 'flow-1',
                functionKind: 'hog_flow',
                parentRunId: 'job-1',
                defaultDateFrom: '2026-01-01',
            })
            scoped.mount()
            expect(scoped.values.filters.date_from).toBe('2026-01-01')
            scoped.unmount()
        })
    })

    describe('sparkline buckets', () => {
        // ClickHouse buckets `toStartOf*` in the project timezone and returns the boundary with that
        // offset. Generating the lookup keys on the UTC grid instead lands them on a different instant,
        // every bucket resolves to 0, and the chart reads "No invocations in this window" while the
        // table below it is full. Both rows below are windows where that happened.
        it.each([
            { tier: 'daily (window over 7 days)', timezone: 'America/Los_Angeles', dateFrom: '-30d', unit: 'day' },
            { tier: 'hourly (half-hour offset project)', timezone: 'Asia/Kolkata', dateFrom: '-7d', unit: 'hour' },
        ] as const)('counts land in the bucket ClickHouse returned: $tier', async ({ timezone, dateFrom, unit }) => {
            // The boundary ClickHouse would return for a run 3 days ago, in the project's zone.
            const bucket = dayjs().tz(timezone).subtract(3, 'day').startOf(unit)
            useMocks({
                post: {
                    // `format()` carries the project's offset, the way the query API serializes it.
                    '/api/environments/:team_id/query/HogQLQuery/': () => [
                        200,
                        { results: [[bucket.format(), 'succeeded', 5]] },
                    ],
                },
            })
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone })

            const logic = hogInvocationsLogic({ id: 'flow-1', functionKind: 'hog_flow' })
            logic.mount()
            logic.actions.setFilters({ date_from: dateFrom })
            await expectLogic(logic).toDispatchActions(['loadSparklineSuccess'])

            const { dates, series } = logic.values.sparkline!
            const index = dates.indexOf(bucket.toISOString())
            expect(index).toBeGreaterThanOrEqual(0)
            expect(series.find((s) => s.name === 'succeeded')!.values[index]).toBe(5)

            logic.unmount()
        })

        it('covers a window spanning a DST transition, one bucket per local day', async () => {
            // 1 Nov 2026 is 25 hours long in America/Los_Angeles. Stepping the instant by 24h drifts
            // off local midnight there, and re-snapping the drifted instant lands back on the same
            // bucket, which silently truncated the range at the transition.
            const timezone = 'America/Los_Angeles'
            useMocks({
                post: {
                    '/api/environments/:team_id/query/HogQLQuery/': () => [200, { results: [] }],
                },
            })
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone })

            const logic = hogInvocationsLogic({ id: 'flow-1', functionKind: 'hog_flow' })
            logic.mount()
            logic.actions.setFilters({ date_from: '2026-10-27', date_to: '2026-11-07' })
            await expectLogic(logic).toDispatchActions(['loadSparklineSuccess'])

            const { dates } = logic.values.sparkline!
            const localDays = dates.map((d) => dayjs(d).tz(timezone).format('MM-DD HH:mm'))
            expect(localDays[0]).toBe('10-27 00:00')
            expect(localDays[localDays.length - 1]).toBe('11-06 00:00')
            expect(new Set(localDays.map((d) => d.slice(6)))).toEqual(new Set(['00:00']))
            expect(new Set(localDays).size).toBe(localDays.length)

            logic.unmount()
        })

        it('falls back to the app context timezone before teamLogic has loaded the team', async () => {
            // `teamLogic` fetches the team when the page ships no app context, and `currentTeam` is
            // null until it lands. Bucketing on UTC there would empty the chart for every non-UTC
            // project, which is the bug this file is about.
            const timezone = 'America/Los_Angeles'
            const bucket = dayjs().tz(timezone).subtract(3, 'day').startOf('day')
            useMocks({
                post: {
                    '/api/environments/:team_id/query/HogQLQuery/': () => [
                        200,
                        { results: [[bucket.format(), 'succeeded', 2]] },
                    ],
                },
            })
            // teamLogic unmounted, so the timezone can only come from app context.
            initKeaTests(false, { ...MOCK_DEFAULT_TEAM, timezone })

            const logic = hogInvocationsLogic({ id: 'flow-1', functionKind: 'hog_flow' })
            logic.mount()
            logic.actions.setFilters({ date_from: '-30d' })
            await expectLogic(logic).toDispatchActions(['loadSparklineSuccess'])

            const { dates, series } = logic.values.sparkline!
            const index = dates.indexOf(bucket.toISOString())
            expect(index).toBeGreaterThanOrEqual(0)
            expect(series.find((s) => s.name === 'succeeded')!.values[index]).toBe(2)
            expect(new Set(dates.map((d) => dayjs(d).tz(timezone).format('HH:mm')))).toEqual(new Set(['00:00']))

            logic.unmount()
        })

        it('sums both passes of a repeated fall-back hour into one bucket', async () => {
            // 01:00 happens twice on 1 Nov in America/Los_Angeles, so ClickHouse returns two rows
            // carrying the same wall clock. Joining on the instant splits them across two buckets
            // and leaves the axis a physical hour short of the runs it holds.
            const timezone = 'America/Los_Angeles'
            useMocks({
                post: {
                    '/api/environments/:team_id/query/HogQLQuery/': () => [
                        200,
                        {
                            results: [
                                ['2026-11-01T01:00:00-07:00', 'succeeded', 1],
                                ['2026-11-01T01:00:00-08:00', 'succeeded', 4],
                            ],
                        },
                    ],
                },
            })
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone })

            const logic = hogInvocationsLogic({ id: 'flow-1', functionKind: 'hog_flow' })
            logic.mount()
            logic.actions.setFilters({ date_from: '2026-10-30', date_to: '2026-11-05' })
            await expectLogic(logic).toDispatchActions(['loadSparklineSuccess'])

            const { dates, series } = logic.values.sparkline!
            const oneAm = dates.filter((d) => dayjs(d).tz(timezone).format('MM-DD HH:mm') === '11-01 01:00')
            expect(oneAm).toHaveLength(1)
            const values = series.find((s) => s.name === 'succeeded')!.values
            expect(values[dates.indexOf(oneAm[0])]).toBe(5)

            logic.unmount()
        })

        it('starts an absolute range on the selected project-local day', async () => {
            // The date picker emits '2026-08-01' with no offset. Reading that as UTC midnight starts a
            // west-of-UTC project the previous evening, so the axis opens on a partial day labelled
            // 31 July and the queried window begins hours before the date the user picked.
            const timezone = 'America/Los_Angeles'
            useMocks({
                post: {
                    '/api/environments/:team_id/query/HogQLQuery/': () => [200, { results: [] }],
                },
            })
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone })

            const logic = hogInvocationsLogic({ id: 'flow-1', functionKind: 'hog_flow' })
            logic.mount()
            logic.actions.setFilters({ date_from: '2026-08-01', date_to: '2026-08-12' })
            await expectLogic(logic).toDispatchActions(['loadSparklineSuccess'])

            const walls = logic.values.sparkline!.dates.map((d) => dayjs(d).tz(timezone).format('MM-DD HH:mm'))
            expect(walls[0]).toBe('08-01 00:00')
            expect(walls[walls.length - 1]).toBe('08-11 00:00')

            logic.unmount()
        })

        it('drops a wall clock that a spring-forward skips', async () => {
            // 02:00 never happens on 14 Mar 2027 in America/Los_Angeles, so no run can carry it.
            // Keeping it would add a bucket nothing can ever fill, sharing an x position with 03:00.
            const timezone = 'America/Los_Angeles'
            useMocks({
                post: {
                    '/api/environments/:team_id/query/HogQLQuery/': () => [200, { results: [] }],
                },
            })
            initKeaTests(true, { ...MOCK_DEFAULT_TEAM, timezone })

            const logic = hogInvocationsLogic({ id: 'flow-1', functionKind: 'hog_flow' })
            logic.mount()
            logic.actions.setFilters({ date_from: '2027-03-12', date_to: '2027-03-17' })
            await expectLogic(logic).toDispatchActions(['loadSparklineSuccess'])

            const { dates } = logic.values.sparkline!
            const walls = dates.map((d) => dayjs(d).tz(timezone).format('MM-DD HH:mm'))
            expect(walls).toContain('03-14 01:00')
            expect(walls).toContain('03-14 03:00')
            expect(walls).not.toContain('03-14 02:00')
            expect(new Set(dates).size).toBe(dates.length)

            logic.unmount()
        })
    })
})
