import { LiveMetricsSlidingWindow } from './LiveMetricsSlidingWindow'

const MINUTE = 60 * 1000

const WALL_CLOCK = '2024-01-15T16:30:00Z'
const WALL_CLOCK_MS = new Date(WALL_CLOCK).getTime()

const relativeTime = (offsetMs: number): string => new Date(WALL_CLOCK_MS + offsetMs).toISOString()
const toUnixSeconds = (isoString: string): number => new Date(isoString).getTime() / 1000

describe('LiveMetricsSlidingWindow', () => {
    const WINDOW_SIZE_MINUTES = 30

    let mockNow: jest.SpyInstance

    beforeEach(() => {
        mockNow = jest.spyOn(Date, 'now').mockReturnValue(WALL_CLOCK_MS)
    })

    afterEach(() => {
        mockNow.mockRestore()
    })

    describe('addDataPoint', () => {
        it('adds pageview data to the correct minute bucket', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const eventTime = relativeTime(-4.5 * MINUTE)

            window.addDataPoint(toUnixSeconds(eventTime), {
                pageviews: 1,
                distinctId: 'user-1',
            })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(1)

            const [bucketTs, bucket] = buckets[0]
            expect(bucketTs).toBe(toUnixSeconds(relativeTime(-5 * MINUTE)))
            expect(bucket.pageviews).toBe(1)
            expect(bucket.uniqueUsers.has('user-1')).toBe(true)
        })

        it('aggregates multiple events in the same minute', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const minuteStart = toUnixSeconds(relativeTime(-5 * MINUTE))

            window.addDataPoint(minuteStart + 10, { pageviews: 1, distinctId: 'user-1' })
            window.addDataPoint(minuteStart + 20, { pageviews: 1, distinctId: 'user-2' })
            window.addDataPoint(minuteStart + 30, { pageviews: 1, distinctId: 'user-1' })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(1)

            const [, bucket] = buckets[0]
            expect(bucket.pageviews).toBe(3)
            expect(bucket.uniqueUsers.size).toBe(2)
        })

        it('creates separate buckets for different minutes', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), { pageviews: 2 })
            window.addDataPoint(toUnixSeconds(relativeTime(-3 * MINUTE)), { pageviews: 3 })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(3)
            expect(buckets[0][1].pageviews).toBe(1)
            expect(buckets[1][1].pageviews).toBe(2)
            expect(buckets[2][1].pageviews).toBe(3)
        })
    })

    describe('prune', () => {
        it('uses wall clock time for pruning, not event timestamp', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), {
                pageviews: 1,
                distinctId: 'user-old',
            })

            let buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(1)

            window.addDataPoint(toUnixSeconds(relativeTime(1 * MINUTE)), {
                pageviews: 1,
                distinctId: 'user-future',
            })

            buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(2)
            expect(buckets.map(([ts]) => ts)).toContain(toUnixSeconds(relativeTime(-30 * MINUTE)))
        })

        it('removes buckets older than the window size based on wall clock', () => {
            mockNow.mockReturnValue(WALL_CLOCK_MS + 1 * MINUTE)

            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), {
                pageviews: 1,
                distinctId: 'user-old',
            })

            expect(window.getSortedBuckets()).toHaveLength(0)
        })

        it('keeps buckets exactly at the window boundary', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), { pageviews: 1 })

            expect(window.getSortedBuckets()).toHaveLength(1)
        })

        it('keeps all buckets within window size', () => {
            const windowSize = 5
            const window = new LiveMetricsSlidingWindow(windowSize)

            for (let i = 1; i <= windowSize; i++) {
                window.addDataPoint(toUnixSeconds(relativeTime(-i * MINUTE)), { pageviews: 1 })
            }

            expect(window.getSortedBuckets()).toHaveLength(windowSize)
        })
    })

    describe('getSortedBuckets', () => {
        it('returns buckets in chronological order regardless of insertion order', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-3 * MINUTE)), { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), { pageviews: 1 })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(3)
            expect(buckets[0][0]).toBe(toUnixSeconds(relativeTime(-5 * MINUTE)))
            expect(buckets[1][0]).toBe(toUnixSeconds(relativeTime(-4 * MINUTE)))
            expect(buckets[2][0]).toBe(toUnixSeconds(relativeTime(-3 * MINUTE)))
        })

        it('returns empty array for empty window', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            expect(window.getSortedBuckets()).toEqual([])
        })
    })

    describe('getTotalPageviews', () => {
        it('sums pageviews across all buckets', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), { pageviews: 5 })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), { pageviews: 10 })
            window.addDataPoint(toUnixSeconds(relativeTime(-3 * MINUTE)), { pageviews: 15 })

            expect(window.getTotalPageviews()).toBe(30)
        })

        it('returns 0 for empty window', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            expect(window.getTotalPageviews()).toBe(0)
        })
    })

    describe('getDeviceTotals', () => {
        it('aggregates device counts across buckets', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                devices: new Map([
                    ['Mobile', 5],
                    ['Desktop', 10],
                ]),
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), {
                devices: new Map([
                    ['Mobile', 3],
                    ['Desktop', 7],
                    ['Tablet', 2],
                ]),
            })

            const totals = window.getDeviceTotals()
            expect(totals.get('Mobile')).toBe(8)
            expect(totals.get('Desktop')).toBe(17)
            expect(totals.get('Tablet')).toBe(2)
        })

        it('returns empty map for empty window', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            expect(window.getDeviceTotals().size).toBe(0)
        })
    })

    describe('getTopPaths', () => {
        it('returns paths sorted by view count descending', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                paths: new Map([
                    ['/home', 10],
                    ['/about', 5],
                    ['/pricing', 20],
                ]),
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), {
                paths: new Map([
                    ['/home', 5],
                    ['/contact', 8],
                ]),
            })

            const topPaths = window.getTopPaths(10)
            expect(topPaths).toEqual([
                { path: '/pricing', views: 20 },
                { path: '/home', views: 15 },
                { path: '/contact', views: 8 },
                { path: '/about', views: 5 },
            ])
        })

        it.each([
            { limit: 1, expectedPaths: ['/pricing'] },
            { limit: 2, expectedPaths: ['/pricing', '/home'] },
            { limit: 3, expectedPaths: ['/pricing', '/home', '/contact'] },
            { limit: 100, expectedPaths: ['/pricing', '/home', '/contact', '/about'] },
        ])('limits results to $limit paths', ({ limit, expectedPaths }) => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                paths: new Map([
                    ['/pricing', 20],
                    ['/home', 15],
                    ['/contact', 8],
                    ['/about', 5],
                ]),
            })

            const topPaths = window.getTopPaths(limit)
            expect(topPaths.map((p) => p.path)).toEqual(expectedPaths)
        })

        it('returns empty array for empty window', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            expect(window.getTopPaths(10)).toEqual([])
        })
    })

    describe('uniqueUsers', () => {
        it('deduplicates distinct_ids within the same bucket', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const minuteStart = toUnixSeconds(relativeTime(-5 * MINUTE))

            window.addDataPoint(minuteStart + 10, { distinctId: 'user-1' })
            window.addDataPoint(minuteStart + 20, { distinctId: 'user-1' })
            window.addDataPoint(minuteStart + 30, { distinctId: 'user-2' })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(1)
            expect(buckets[0][1].uniqueUsers.size).toBe(2)
            expect(buckets[0][1].uniqueUsers.has('user-1')).toBe(true)
            expect(buckets[0][1].uniqueUsers.has('user-2')).toBe(true)
        })

        it('handles distinctIds array with duplicates', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                distinctIds: ['user-1', 'user-2', 'user-1', 'user-3', 'user-2'],
            })

            const buckets = window.getSortedBuckets()
            expect(buckets[0][1].uniqueUsers.size).toBe(3)
        })

        it('tracks users separately per bucket (no cross-bucket deduplication)', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), { distinctId: 'user-1' })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), { distinctId: 'user-1' })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(2)
            expect(buckets[0][1].uniqueUsers.has('user-1')).toBe(true)
            expect(buckets[1][1].uniqueUsers.has('user-1')).toBe(true)
        })

        it('merges uniqueUsers set from data', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const minuteStart = toUnixSeconds(relativeTime(-5 * MINUTE))

            window.addDataPoint(minuteStart, {
                uniqueUsers: new Set(['user-1', 'user-2']),
            })
            window.addDataPoint(minuteStart + 30, {
                uniqueUsers: new Set(['user-2', 'user-3']),
            })

            const buckets = window.getSortedBuckets()
            expect(buckets[0][1].uniqueUsers.size).toBe(3)
        })
    })

    describe('edge cases', () => {
        it('handles single event', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                pageviews: 1,
                distinctId: 'user-1',
            })

            expect(window.getTotalPageviews()).toBe(1)
            expect(window.getSortedBuckets()).toHaveLength(1)
        })

        it('handles multiple events at exact same timestamp', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const timestamp = toUnixSeconds(relativeTime(-5 * MINUTE))

            window.addDataPoint(timestamp, { pageviews: 1, distinctId: 'user-1' })
            window.addDataPoint(timestamp, { pageviews: 1, distinctId: 'user-2' })
            window.addDataPoint(timestamp, { pageviews: 1, distinctId: 'user-1' })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(1)
            expect(buckets[0][1].pageviews).toBe(3)
            expect(buckets[0][1].uniqueUsers.size).toBe(2)
        })
    })
})
