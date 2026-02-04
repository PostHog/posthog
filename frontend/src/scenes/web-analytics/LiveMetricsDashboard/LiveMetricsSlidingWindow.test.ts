import { LiveMetricsSlidingWindow } from './LiveMetricsSlidingWindow'

const MINUTE = 60 * 1000

const getDeviceCount = (
    breakdown: { device: string; count: number; percentage: number }[],
    deviceType: string
): number | undefined => breakdown.find((d) => d.device === deviceType)?.count

const WALL_CLOCK = '2026-01-16T16:30:00Z'
const WALL_CLOCK_MS = new Date(WALL_CLOCK).getTime()

const relativeTime = (offsetMs: number): string => new Date(WALL_CLOCK_MS + offsetMs).toISOString()
const toUnixSeconds = (isoString: string): number => new Date(isoString).getTime() / 1000

describe('LiveMetricsSlidingWindow', () => {
    const WINDOW_SIZE_MINUTES = 30

    let mockNow: jest.SpyInstance
    let currentTimeMs = WALL_CLOCK_MS

    const tickMinute = (): void => {
        currentTimeMs += MINUTE
        mockNow.mockReturnValue(currentTimeMs)
    }

    beforeEach(() => {
        currentTimeMs = WALL_CLOCK_MS
        mockNow = jest.spyOn(Date, 'now').mockReturnValue(WALL_CLOCK_MS)
    })

    afterEach(() => {
        mockNow.mockRestore()
    })

    describe('addDataPoint', () => {
        it('floors event timestamp to minute boundary when assigning bucket', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const eventTime = relativeTime(-4.5 * MINUTE)

            window.addDataPoint(toUnixSeconds(eventTime), 'user-1', {
                pageviews: 1,
                pathname: '/home',
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

            window.addDataPoint(minuteStart + 10, 'user-1', { pageviews: 1 })
            window.addDataPoint(minuteStart + 20, 'user-2', { pageviews: 1 })
            window.addDataPoint(minuteStart + 30, 'user-1', { pageviews: 1 })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(1)

            const [, bucket] = buckets[0]
            expect(bucket.pageviews).toBe(3)
            expect(bucket.uniqueUsers.size).toBe(2)
        })

        it('creates separate buckets for different minutes', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-2', { pageviews: 2 })
            window.addDataPoint(toUnixSeconds(relativeTime(-3 * MINUTE)), 'user-3', { pageviews: 3 })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(3)
            expect(buckets[0][1].pageviews).toBe(1)
            expect(buckets[1][1].pageviews).toBe(2)
            expect(buckets[2][1].pageviews).toBe(3)
        })

        it('aggregates multiple events at exact same timestamp', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const timestamp = toUnixSeconds(relativeTime(-5 * MINUTE))

            window.addDataPoint(timestamp, 'user-1', { pageviews: 1 })
            window.addDataPoint(timestamp, 'user-2', { pageviews: 1 })
            window.addDataPoint(timestamp, 'user-1', { pageviews: 1 })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(1)
            expect(buckets[0][1].pageviews).toBe(3)
            expect(buckets[0][1].uniqueUsers.size).toBe(2)
        })
    })

    describe('prune', () => {
        it('does not prune based on event timestamp alone', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'user-old', { pageviews: 1 })

            let buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(1)

            window.addDataPoint(toUnixSeconds(relativeTime(1 * MINUTE)), 'user-future', { pageviews: 1 })

            buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(2)
            expect(buckets.map(([ts]) => ts)).toContain(toUnixSeconds(relativeTime(-30 * MINUTE)))
        })

        it('removes buckets older than the window size when wall clock advances', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'user-old', { pageviews: 1 })
            tickMinute()
            window.addDataPoint(toUnixSeconds(relativeTime(-1 * MINUTE)), 'user-new', { pageviews: 1 })

            expect(window.getSortedBuckets()).toHaveLength(1)
        })

        it('keeps buckets exactly at the window boundary', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'user-1', { pageviews: 1 })

            expect(window.getSortedBuckets()).toHaveLength(1)
        })

        it('keeps all buckets within window size', () => {
            const windowSize = 5
            const window = new LiveMetricsSlidingWindow(windowSize)

            for (let i = 1; i <= windowSize; i++) {
                window.addDataPoint(toUnixSeconds(relativeTime(-i * MINUTE)), `user-${i}`, { pageviews: 1 })
            }

            expect(window.getSortedBuckets()).toHaveLength(windowSize)
        })
    })

    describe('getSortedBuckets', () => {
        it('returns buckets in chronological order regardless of insertion order', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-3 * MINUTE)), 'user-1', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-3', { pageviews: 1 })

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

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 5 })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-2', { pageviews: 10 })
            window.addDataPoint(toUnixSeconds(relativeTime(-3 * MINUTE)), 'user-3', { pageviews: 15 })

            expect(window.getTotalPageviews()).toBe(30)
        })

        it('returns 0 for empty window', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            expect(window.getTotalPageviews()).toBe(0)
        })
    })

    describe('getDeviceBreakdown', () => {
        it('aggregates device counts across buckets', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.extendBucketData(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                pageviews: 0,
                devices: new Map([
                    ['Mobile', new Set(['device-1', 'device-2', 'device-3'])],
                    ['Desktop', new Set(['device-4', 'device-5'])],
                ]),
                paths: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
            })

            window.extendBucketData(toUnixSeconds(relativeTime(-4 * MINUTE)), {
                pageviews: 0,
                devices: new Map([
                    ['Mobile', new Set(['device-6', 'device-7', 'device-8'])],
                    ['Desktop', new Set(['device-9', 'device-10', 'device-11'])],
                    ['Tablet', new Set(['device-12', 'device-13'])],
                ]),
                paths: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
            })

            const breakdown = window.getDeviceBreakdown()
            expect(getDeviceCount(breakdown, 'Mobile')).toBe(6)
            expect(getDeviceCount(breakdown, 'Desktop')).toBe(5)
            expect(getDeviceCount(breakdown, 'Tablet')).toBe(2)
        })

        it('deduplicates devices across buckets', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.extendBucketData(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                pageviews: 0,
                devices: new Map([['Mobile', new Set(['device-1', 'device-2'])]]),
                paths: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
            })
            window.extendBucketData(toUnixSeconds(relativeTime(-4 * MINUTE)), {
                pageviews: 0,
                devices: new Map([['Mobile', new Set(['device-1', 'device-3'])]]),
                paths: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
            })

            const breakdown = window.getDeviceBreakdown()
            expect(getDeviceCount(breakdown, 'Mobile')).toBe(3)
        })

        it('returns empty array for empty window', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            expect(window.getDeviceBreakdown()).toEqual([])
        })

        it('includes percentage and sorts by count descending', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.extendBucketData(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                pageviews: 0,
                devices: new Map([
                    ['Mobile', new Set(['device-1', 'device-2', 'device-3'])],
                    ['Desktop', new Set(['device-4', 'device-5', 'device-6', 'device-7'])],
                    ['Tablet', new Set(['device-8'])],
                ]),
                paths: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
            })

            const breakdown = window.getDeviceBreakdown()
            expect(breakdown).toHaveLength(3)
            expect(breakdown[0]).toEqual({ device: 'Desktop', count: 4, percentage: 50 })
            expect(breakdown[1]).toEqual({ device: 'Mobile', count: 3, percentage: 37.5 })
            expect(breakdown[2]).toEqual({ device: 'Tablet', count: 1, percentage: 12.5 })
        })
    })

    describe('getTopPaths', () => {
        it('returns paths sorted by view count descending', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.extendBucketData(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                pageviews: 0,
                devices: new Map(),
                paths: new Map([
                    ['/home', 10],
                    ['/about', 5],
                    ['/pricing', 20],
                ]),
                browsers: new Map(),
                uniqueUsers: new Set(),
            })
            window.extendBucketData(toUnixSeconds(relativeTime(-4 * MINUTE)), {
                pageviews: 0,
                devices: new Map(),
                paths: new Map([
                    ['/home', 5],
                    ['/contact', 8],
                ]),
                browsers: new Map(),
                uniqueUsers: new Set(),
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

            window.extendBucketData(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                pageviews: 0,
                devices: new Map(),
                paths: new Map([
                    ['/pricing', 20],
                    ['/home', 15],
                    ['/contact', 8],
                    ['/about', 5],
                ]),
                browsers: new Map(),
                uniqueUsers: new Set(),
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

            window.addDataPoint(minuteStart + 10, 'user-1', { pageviews: 0 })
            window.addDataPoint(minuteStart + 20, 'user-1', { pageviews: 0 })
            window.addDataPoint(minuteStart + 30, 'user-2', { pageviews: 0 })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(1)
            expect(buckets[0][1].uniqueUsers.size).toBe(2)
            expect(buckets[0][1].uniqueUsers.has('user-1')).toBe(true)
            expect(buckets[0][1].uniqueUsers.has('user-2')).toBe(true)
        })

        it('tracks users separately per bucket (no cross-bucket deduplication)', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 0 })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-1', { pageviews: 0 })

            const buckets = window.getSortedBuckets()
            expect(buckets).toHaveLength(2)
            expect(buckets[0][1].uniqueUsers.has('user-1')).toBe(true)
            expect(buckets[1][1].uniqueUsers.has('user-1')).toBe(true)
        })

        it('merges uniqueUsers set from extendBucketData', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const minuteStart = toUnixSeconds(relativeTime(-5 * MINUTE))

            window.extendBucketData(minuteStart, {
                pageviews: 0,
                devices: new Map(),
                paths: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(['user-1', 'user-2']),
            })
            window.extendBucketData(minuteStart, {
                pageviews: 0,
                devices: new Map(),
                paths: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(['user-2', 'user-3']),
            })

            const buckets = window.getSortedBuckets()
            expect(buckets[0][1].uniqueUsers.size).toBe(3)
        })
    })

    describe('device tracking via addDataPoint', () => {
        it('tracks devices when device info is provided', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', {
                pageviews: 1,
                pathname: '/home',
                device: { deviceId: 'device-1', deviceType: 'Mobile' },
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', {
                pageviews: 1,
                pathname: '/about',
                device: { deviceId: 'device-2', deviceType: 'Desktop' },
            })

            const breakdown = window.getDeviceBreakdown()
            expect(getDeviceCount(breakdown, 'Mobile')).toBe(1)
            expect(getDeviceCount(breakdown, 'Desktop')).toBe(1)
        })

        it('deduplicates same device across multiple events', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', {
                pageviews: 1,
                pathname: '/home',
                device: { deviceId: 'device-1', deviceType: 'Mobile' },
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', {
                pageviews: 1,
                pathname: '/about',
                device: { deviceId: 'device-1', deviceType: 'Mobile' },
            })

            const breakdown = window.getDeviceBreakdown()
            expect(getDeviceCount(breakdown, 'Mobile')).toBe(1)
        })

        it('decrements device count when buckets are pruned', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'user-1', {
                pageviews: 1,
                device: { deviceId: 'device-1', deviceType: 'Mobile' },
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', {
                pageviews: 1,
                device: { deviceId: 'device-2', deviceType: 'Mobile' },
            })

            expect(getDeviceCount(window.getDeviceBreakdown(), 'Mobile')).toBe(2)

            tickMinute()

            window.addDataPoint(toUnixSeconds(relativeTime(MINUTE)), 'user-3', {
                pageviews: 1,
                device: { deviceId: 'device-3', deviceType: 'Desktop' },
            })

            const breakdown = window.getDeviceBreakdown()
            expect(getDeviceCount(breakdown, 'Mobile')).toBe(1)
            expect(getDeviceCount(breakdown, 'Desktop')).toBe(1)
        })

        it('keeps device count when device exists in multiple buckets and one is pruned', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'user-1', {
                pageviews: 1,
                device: { deviceId: 'device-1', deviceType: 'Mobile' },
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', {
                pageviews: 1,
                device: { deviceId: 'device-1', deviceType: 'Mobile' },
            })

            expect(getDeviceCount(window.getDeviceBreakdown(), 'Mobile')).toBe(1)

            tickMinute()

            window.addDataPoint(toUnixSeconds(relativeTime(MINUTE)), 'user-2', {
                pageviews: 1,
                device: { deviceId: 'device-2', deviceType: 'Desktop' },
            })

            const breakdown = window.getDeviceBreakdown()
            expect(getDeviceCount(breakdown, 'Mobile')).toBe(1)
            expect(getDeviceCount(breakdown, 'Desktop')).toBe(1)
        })

        it('counts cookieless users as separate devices when they have different distinct_ids', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const COOKIELESS_DEVICE_ID = '$posthog_cookieless'

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', {
                pageviews: 1,
                device: { deviceId: `${COOKIELESS_DEVICE_ID}_user-1`, deviceType: 'Mobile' },
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', {
                pageviews: 1,
                device: { deviceId: `${COOKIELESS_DEVICE_ID}_user-2`, deviceType: 'Mobile' },
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-3', {
                pageviews: 1,
                device: { deviceId: `${COOKIELESS_DEVICE_ID}_user-3`, deviceType: 'Desktop' },
            })

            const breakdown = window.getDeviceBreakdown()
            expect(getDeviceCount(breakdown, 'Mobile')).toBe(2)
            expect(getDeviceCount(breakdown, 'Desktop')).toBe(1)
        })
    })

    describe('path tracking via addDataPoint', () => {
        it('tracks paths when pathname is provided', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 1, pathname: '/home' })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', { pageviews: 1, pathname: '/home' })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-3', {
                pageviews: 1,
                pathname: '/about',
            })

            const topPaths = window.getTopPaths(10)
            expect(topPaths).toEqual([
                { path: '/home', views: 2 },
                { path: '/about', views: 1 },
            ])
        })
    })

    describe('getTotalUniqueUsers', () => {
        it('returns deduplicated user count across all buckets', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-1', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-3', { pageviews: 1 })

            expect(window.getTotalUniqueUsers()).toBe(3)
        })

        it('returns 0 for empty window', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            expect(window.getTotalUniqueUsers()).toBe(0)
        })

        it('decrements user count when buckets are pruned', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'user-1', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', { pageviews: 1 })

            expect(window.getTotalUniqueUsers()).toBe(2)

            tickMinute()

            window.addDataPoint(toUnixSeconds(relativeTime(MINUTE)), 'user-3', { pageviews: 1 })

            expect(window.getTotalUniqueUsers()).toBe(2)
            expect(window.getSortedBuckets()).toHaveLength(2)
        })

        it('keeps user count when user exists in multiple buckets and one is pruned', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'user-1', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 1 })

            expect(window.getTotalUniqueUsers()).toBe(1)

            tickMinute()

            window.addDataPoint(toUnixSeconds(relativeTime(MINUTE)), 'user-2', { pageviews: 1 })

            expect(window.getTotalUniqueUsers()).toBe(2)
        })
    })
})
