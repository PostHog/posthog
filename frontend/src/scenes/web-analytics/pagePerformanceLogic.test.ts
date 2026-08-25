import { dayjs } from 'lib/dayjs'

import { CompareFilter } from '~/queries/schema/schema-general'

import {
    PagePerformanceWindow,
    buildGoogleSearchConsoleQuery,
    buildPagePerformanceTableQuery,
    formatShare,
    mergePagePerformanceSeries,
    parsePagePerformanceOverviewResponse,
    resolvePagePerformanceBucket,
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

    it.each([
        { name: 'a small share keeps a decimal rather than rounding to zero', part: 2, whole: 1430, expected: '0.1%' },
        { name: 'a share just under ten percent keeps a decimal', part: 137, whole: 1430, expected: '9.6%' },
        { name: 'a large share drops the decimal', part: 172, whole: 1430, expected: '12%' },
        { name: 'nothing to show when the part is zero', part: 0, whole: 1430, expected: null },
        { name: 'nothing to show when the whole is zero', part: 12, whole: 0, expected: null },
    ])('$name', ({ part, whole, expected }) => {
        expect(formatShare(part, whole)).toBe(expected)
    })

    describe('overview series', () => {
        const comparedWindow: PagePerformanceWindow = {
            currentFrom: dayjs.tz('2026-08-03', timezone),
            currentTo: dayjs.tz('2026-08-05', timezone).endOf('day'),
            previousFrom: dayjs.tz('2026-08-01', timezone),
            previousTo: dayjs.tz('2026-08-03', timezone),
            timezone,
        }
        const humanColumns = ['bucket', 'visitors', 'visitors_previous', 'pages']

        it('reads totals from the grouping-sets row instead of summing buckets', () => {
            const parsed = parsePagePerformanceOverviewResponse(
                humanColumns,
                [
                    ['1970-01-01 00:00:00', 90, 40, 12],
                    ['2026-08-03 00:00:00', 50, 0, 7],
                    ['2026-08-04 00:00:00', 60, 0, 8],
                ],
                comparedWindow
            )

            // Summing the buckets would give 110 visitors — per-bucket uniques double-count returning people.
            expect(parsed.totals.visitors).toBe(90)
            expect(parsed.totals.visitors_previous).toBe(40)
            expect(parsed.totals.pages).toBe(12)
            expect(parsed.buckets).toHaveLength(2)
        })

        it('keeps comparison-period buckets out of the series', () => {
            const parsed = parsePagePerformanceOverviewResponse(
                humanColumns,
                [
                    ['1970-01-01 00:00:00', 90, 40, 12],
                    ['2026-08-01 00:00:00', 0, 25, 0],
                    ['2026-08-02 00:00:00', 0, 15, 0],
                    ['2026-08-03 00:00:00', 50, 0, 7],
                ],
                comparedWindow
            )

            expect(parsed.buckets.map((point) => point.bucket.format('YYYY-MM-DD'))).toEqual(['2026-08-03'])
        })

        it('aligns crawler buckets onto the same axis when a query misses a bucket', () => {
            const human = parsePagePerformanceOverviewResponse(
                ['bucket', 'visitors', 'google', 'llm'],
                [
                    ['1970-01-01 00:00:00', 90, 30, 5],
                    ['2026-08-03 00:00:00', 50, 20, 3],
                    ['2026-08-05 00:00:00', 40, 10, 2],
                ],
                comparedWindow
            )
            const crawler = parsePagePerformanceOverviewResponse(
                ['bucket', 'crawls'],
                [
                    ['1970-01-01 00:00:00', 700],
                    ['2026-08-04 00:00:00', 700],
                ],
                comparedWindow
            )

            expect(mergePagePerformanceSeries(human, crawler, 'day')).toEqual([
                { label: 'Aug 3', visitors: 50, google: 20, llm: 3, crawls: 0 },
                { label: 'Aug 4', visitors: 0, google: 0, llm: 0, crawls: 700 },
                { label: 'Aug 5', visitors: 40, google: 10, llm: 2, crawls: 0 },
            ])
        })

        it.each([
            { name: 'a single day gets hourly buckets', dateFrom: '2026-08-05', expected: 'hour' },
            { name: 'a week gets daily buckets', dateFrom: '2026-07-30', expected: 'day' },
            { name: 'a year gets weekly buckets', dateFrom: '2025-08-06', expected: 'week' },
        ])('$name', ({ dateFrom, expected }) => {
            const window: PagePerformanceWindow = {
                currentFrom: dayjs.tz(dateFrom, timezone),
                currentTo: dayjs.tz('2026-08-06', timezone),
                previousFrom: null,
                previousTo: null,
                timezone,
            }

            expect(resolvePagePerformanceBucket(window)).toBe(expected)
        })

        it('falls back to weekly buckets for an unbounded range', () => {
            const window: PagePerformanceWindow = {
                currentFrom: null,
                currentTo: dayjs.tz('2026-08-06', timezone),
                previousFrom: null,
                previousTo: null,
                timezone,
            }

            expect(resolvePagePerformanceBucket(window)).toBe('week')
        })
    })
})
