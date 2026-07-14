import type { LiveEvent } from '~/types'

import { LiveWidgetSlidingWindow } from './LiveWidgetSlidingWindow'

const WALL_CLOCK = '2026-01-16T16:30:00Z'
const WALL_CLOCK_MS = new Date(WALL_CLOCK).getTime()
const MINUTE = 60 * 1000

const relativeTime = (offsetMs: number): string => new Date(WALL_CLOCK_MS + offsetMs).toISOString()

const pageview = (timestamp: string, properties: Record<string, unknown> = {}): LiveEvent =>
    ({
        uuid: `uuid-${timestamp}-${JSON.stringify(properties)}`,
        event: '$pageview',
        timestamp,
        distinct_id: 'user-1',
        team_id: 1,
        created_at: timestamp,
        properties,
    }) as LiveEvent

// Mirrors the web analytics widgets: a skip-when-absent domain and a fallback-value domain.
const makeWindow = (): LiveWidgetSlidingWindow<'paths' | 'referrers'> =>
    new LiveWidgetSlidingWindow({
        windowMinutes: 30,
        breakdowns: {
            paths: (event) => {
                const pathname = event.properties?.$pathname
                return typeof pathname === 'string' && pathname !== '' ? pathname : null
            },
            referrers: (event) => {
                const referrer = event.properties?.$referring_domain
                return typeof referrer === 'string' && referrer !== '' ? referrer : '$direct'
            },
        },
    })

describe('LiveWidgetSlidingWindow', () => {
    it('drops streamed events at or before a domain seed generatedAt so re-seeds never double count', () => {
        const window = makeWindow()
        const generatedAt = relativeTime(-1 * MINUTE)
        window.mergeCountSeed([{ minute: relativeTime(-2 * MINUTE), count: 5 }], generatedAt)

        window.addEvent(pageview(relativeTime(-90 * 1000), { $pathname: '/before' })) // before generatedAt
        window.addEvent(pageview(generatedAt, { $pathname: '/at' })) // exactly at generatedAt
        window.addEvent(pageview(relativeTime(-30 * 1000), { $pathname: '/after' })) // after generatedAt

        expect(window.totalCount()).toBe(6)
    })

    it('never lets a lagging or empty re-seed wipe stream-accumulated counts', () => {
        const window = makeWindow()
        window.addEvent(pageview(relativeTime(-1 * MINUTE), { $pathname: '/live', $referring_domain: 'google.com' }))
        window.addEvent(pageview(relativeTime(-1 * MINUTE), { $pathname: '/live' }))

        // ClickHouse ingestion lags the stream: the re-seed comes back empty.
        window.mergeCountSeed([], relativeTime(0))
        window.mergeBreakdownSeed('paths', [], relativeTime(0))
        window.mergeBreakdownSeed('referrers', [], relativeTime(0))

        expect(window.totalCount()).toBe(2)
        expect(window.breakdownTotals('paths')).toEqual([{ value: '/live', views: 2 }])
        expect(window.breakdownTotals('referrers')).toEqual([
            { value: '$direct', views: 1 },
            { value: 'google.com', views: 1 },
        ])
    })

    it('does not double count when a caught-up re-seed includes events the stream already counted', () => {
        const window = makeWindow()
        window.addEvent(pageview(relativeTime(-1 * MINUTE), { $pathname: '/docs' }))
        window.addEvent(pageview(relativeTime(-1 * MINUTE), { $pathname: '/docs' }))

        // Server truth for that minute covers the streamed events plus one the stream missed.
        window.mergeCountSeed([{ minute: relativeTime(-1 * MINUTE), count: 3 }], relativeTime(0))
        window.mergeBreakdownSeed(
            'paths',
            [{ minute: relativeTime(-1 * MINUTE), value: '/docs', views: 3 }],
            relativeTime(0)
        )

        expect(window.totalCount()).toBe(3)
        expect(window.breakdownTotals('paths')).toEqual([{ value: '/docs', views: 3 }])
    })

    it('keeps domain seeds independent: seeding one domain does not clear counts or other domains', () => {
        const window = makeWindow()
        window.mergeCountSeed([{ minute: relativeTime(-2 * MINUTE), count: 3 }], relativeTime(0))
        window.addEvent(pageview(relativeTime(-5 * MINUTE), { $referring_domain: 'google.com' }))

        window.mergeBreakdownSeed(
            'paths',
            [{ minute: relativeTime(-2 * MINUTE), value: '/docs', views: 7 }],
            relativeTime(0)
        )

        expect(window.totalCount()).toBe(3)
        expect(window.breakdownTotals('paths')).toEqual([{ value: '/docs', views: 7 }])
        expect(window.breakdownTotals('referrers')).toEqual([{ value: 'google.com', views: 1 }])
    })

    it.each([
        ['missing referrer', {}],
        ['empty referrer', { $referring_domain: '' }],
    ])('counts an extractor fallback value for %s while a null extractor skips the domain', (_name, properties) => {
        const window = makeWindow()
        window.addEvent(pageview(relativeTime(-1 * MINUTE), properties))

        // No $pathname → paths extractor returns null → the event is skipped for that domain only.
        expect(window.breakdownTotals('paths')).toEqual([])
        expect(window.breakdownTotals('referrers')).toEqual([{ value: '$direct', views: 1 }])
    })

    it('aggregates breakdown views across minutes and sorts by views descending', () => {
        const window = makeWindow()
        window.mergeBreakdownSeed(
            'paths',
            [
                { minute: relativeTime(-3 * MINUTE), value: '/a', views: 1 },
                { minute: relativeTime(-2 * MINUTE), value: '/b', views: 2 },
                { minute: relativeTime(-1 * MINUTE), value: '/a', views: 2 },
            ],
            relativeTime(0)
        )

        expect(window.breakdownTotals('paths')).toEqual([
            { value: '/a', views: 3 },
            { value: '/b', views: 2 },
        ])
    })

    it('prunes minutes older than the window from every domain', () => {
        const window = makeWindow()
        window.mergeCountSeed(
            [
                { minute: relativeTime(-40 * MINUTE), count: 9 },
                { minute: relativeTime(-5 * MINUTE), count: 1 },
            ],
            relativeTime(0)
        )
        window.mergeBreakdownSeed(
            'referrers',
            [
                { minute: relativeTime(-40 * MINUTE), value: 'old.com', views: 9 },
                { minute: relativeTime(-5 * MINUTE), value: 'new.com', views: 1 },
            ],
            relativeTime(0)
        )

        window.prune(WALL_CLOCK_MS / 1000)

        expect(window.totalCount()).toBe(1)
        expect(window.breakdownTotals('referrers')).toEqual([{ value: 'new.com', views: 1 }])
    })
})
