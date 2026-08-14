import { dayjs } from 'lib/dayjs'

import { CompareFilter } from '~/queries/schema/schema-general'

import {
    PagePerformanceWindow,
    buildGoogleSearchConsoleQuery,
    buildPagePerformanceTableQuery,
    resolvePagePerformanceWindow,
} from './pagePerformanceLogic'
import { DateFilterState } from './webAnalyticsLogic'

const dateFilter = (dateFrom: string | null, dateTo: string | null): DateFilterState => ({
    dateFrom,
    dateTo,
    interval: 'day',
    isIntervalManuallySet: false,
})

describe('pagePerformanceLogic', () => {
    const timezone = 'America/Chicago'
    const now = dayjs.tz('2026-08-13 12:00:00', timezone)

    it.each([
        {
            name: 'keeps all-time ranges unbounded and disables comparison',
            dates: dateFilter('all', null),
            compare: { compare: true } as CompareFilter,
            expectedCurrentFrom: null,
            expectedCurrentTo: '2026-08-13 12:00:00',
            expectedPreviousFrom: null,
            expectedPreviousTo: null,
        },
        {
            name: 'includes the full explicit end date in the team timezone',
            dates: dateFilter('2026-08-01', '2026-08-05'),
            compare: { compare: false } as CompareFilter,
            expectedCurrentFrom: '2026-08-01 00:00:00',
            expectedCurrentTo: '2026-08-05 23:59:59',
            expectedPreviousFrom: null,
            expectedPreviousTo: null,
        },
        {
            name: 'anchors a custom comparison range at the current start',
            dates: dateFilter('2026-08-01', '2026-08-05'),
            compare: { compare: true, compare_to: '-1y' } as CompareFilter,
            expectedCurrentFrom: '2026-08-01 00:00:00',
            expectedCurrentTo: '2026-08-05 23:59:59',
            expectedPreviousFrom: '2025-08-01 00:00:00',
            expectedPreviousTo: '2025-08-05 23:59:59',
        },
    ])(
        '$name',
        ({ dates, compare, expectedCurrentFrom, expectedCurrentTo, expectedPreviousFrom, expectedPreviousTo }) => {
            const window = resolvePagePerformanceWindow(dates, compare, timezone, now)

            expect(window.currentFrom?.format('YYYY-MM-DD HH:mm:ss') ?? null).toBe(expectedCurrentFrom)
            expect(window.currentTo.format('YYYY-MM-DD HH:mm:ss')).toBe(expectedCurrentTo)
            expect(window.previousFrom?.format('YYYY-MM-DD HH:mm:ss') ?? null).toBe(expectedPreviousFrom)
            expect(window.previousTo?.format('YYYY-MM-DD HH:mm:ss') ?? null).toBe(expectedPreviousTo)
        }
    )

    it('bounds the leaderboard query and attributes duration to the previous page', () => {
        const window: PagePerformanceWindow = {
            currentFrom: dayjs.tz('2026-08-01', timezone),
            currentTo: dayjs.tz('2026-08-05', timezone).endOf('day'),
            previousFrom: null,
            previousTo: null,
            timezone,
        }
        const query = buildPagePerformanceTableQuery(
            window,
            { column: 'visitors', direction: 'DESC' },
            null,
            'properties.$pathname',
            'properties.$prev_pageview_pathname',
            ['one.example/pricing', 'two.example/pricing']
        )

        expect(query).toContain(
            "concat(coalesce(properties.$host, ''), properties.$pathname) IN ('one.example/pricing', 'two.example/pricing')"
        )
        expect(query).toContain("event IN ('$pageview', '$screen', '$pageleave')")
        expect(query).toContain('properties.$prev_pageview_pathname')
        expect(query).toContain('LEFT JOIN')
        expect(query).toContain('HAVING uniqIf')
        expect(query).not.toContain('OR countIf')
    })

    it('builds an exact, date-bounded Search Console query with escaped identifiers', () => {
        const window: PagePerformanceWindow = {
            currentFrom: dayjs.tz('2026-08-01', timezone),
            currentTo: dayjs.tz('2026-08-05', timezone).endOf('day'),
            previousFrom: null,
            previousTo: null,
            timezone,
        }
        const query = buildGoogleSearchConsoleQuery('gsc_demo.search table', 'example.com/docs/:id', window, true, [
            { regex: '/docs/[0-9]+', alias: '/docs/:id' },
        ])

        expect(query).toContain('FROM gsc_demo."search table"')
        expect(query).toContain(
            "concat(domain(page), replaceRegexpAll(path(page), '/docs/[0-9]+', '/docs/:id')) = 'example.com/docs/:id'"
        )
        expect(query).toContain("toDate(date) >= toDate('2026-08-01 00:00:00')")
        expect(query).toContain("toDate(date) <= toDate('2026-08-05 23:59:59')")
        expect(query).not.toContain('ILIKE')
    })
})
