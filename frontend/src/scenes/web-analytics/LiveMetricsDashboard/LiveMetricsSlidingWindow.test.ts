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
            window.prune()

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
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map([
                    ['Mobile', new Set(['device-1', 'device-2', 'device-3'])],
                    ['Desktop', new Set(['device-4', 'device-5'])],
                ]),
                paths: new Map(),
                referrers: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map<string, Set<string>>(),
            })

            window.extendBucketData(toUnixSeconds(relativeTime(-4 * MINUTE)), {
                pageviews: 0,
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map([
                    ['Mobile', new Set(['device-6', 'device-7', 'device-8'])],
                    ['Desktop', new Set(['device-9', 'device-10', 'device-11'])],
                    ['Tablet', new Set(['device-12', 'device-13'])],
                ]),
                paths: new Map(),
                referrers: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map<string, Set<string>>(),
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
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map([['Mobile', new Set(['device-1', 'device-2'])]]),
                paths: new Map(),
                referrers: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map<string, Set<string>>(),
            })
            window.extendBucketData(toUnixSeconds(relativeTime(-4 * MINUTE)), {
                pageviews: 0,
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map([['Mobile', new Set(['device-1', 'device-3'])]]),
                paths: new Map(),
                referrers: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map<string, Set<string>>(),
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
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map([
                    ['Mobile', new Set(['device-1', 'device-2', 'device-3'])],
                    ['Desktop', new Set(['device-4', 'device-5', 'device-6', 'device-7'])],
                    ['Tablet', new Set(['device-8'])],
                ]),
                paths: new Map(),
                referrers: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map<string, Set<string>>(),
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
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map(),
                paths: new Map([
                    ['/home', 10],
                    ['/about', 5],
                    ['/pricing', 20],
                ]),
                referrers: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map<string, Set<string>>(),
            })
            window.extendBucketData(toUnixSeconds(relativeTime(-4 * MINUTE)), {
                pageviews: 0,
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map(),
                paths: new Map([
                    ['/home', 5],
                    ['/contact', 8],
                ]),
                referrers: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map<string, Set<string>>(),
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
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map(),
                paths: new Map([
                    ['/pricing', 20],
                    ['/home', 15],
                    ['/contact', 8],
                    ['/about', 5],
                ]),
                referrers: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map<string, Set<string>>(),
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
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map(),
                paths: new Map(),
                referrers: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(['user-1', 'user-2']),
                countries: new Map<string, Set<string>>(),
            })
            window.extendBucketData(minuteStart, {
                pageviews: 0,
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map(),
                paths: new Map(),
                referrers: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(['user-2', 'user-3']),
                countries: new Map<string, Set<string>>(),
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
            window.prune()

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
            window.prune()

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
            window.prune()

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
            window.prune()

            expect(window.getTotalUniqueUsers()).toBe(2)
        })
    })

    describe('country tracking via addGeoDataPoint', () => {
        const getCountryCount = (
            breakdown: { country: string; count: number; percentage: number }[],
            countryCode: string
        ): number | undefined => breakdown.find((c) => c.country === countryCode)?.count

        it('tracks unique users per country', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'US', 'user-1')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'US', 'user-2')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'GB', 'user-3')

            const breakdown = window.getCountryBreakdown()
            expect(getCountryCount(breakdown, 'US')).toBe(2)
            expect(getCountryCount(breakdown, 'GB')).toBe(1)
        })

        it('deduplicates same user in same country within a bucket', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'US', 'user-1')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'US', 'user-1')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'US', 'user-1')

            const breakdown = window.getCountryBreakdown()
            expect(getCountryCount(breakdown, 'US')).toBe(1)
        })

        it('deduplicates users across buckets', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'US', 'user-1')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'US', 'user-1')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'US', 'user-2')

            const breakdown = window.getCountryBreakdown()
            expect(getCountryCount(breakdown, 'US')).toBe(2)
        })

        it('decrements country count when buckets are pruned', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addGeoDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'US', 'user-1')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'US', 'user-2')

            expect(getCountryCount(window.getCountryBreakdown(), 'US')).toBe(2)

            tickMinute()

            window.addGeoDataPoint(toUnixSeconds(relativeTime(MINUTE)), 'GB', 'user-3')
            window.prune()

            const breakdown = window.getCountryBreakdown()
            expect(getCountryCount(breakdown, 'US')).toBe(1)
            expect(getCountryCount(breakdown, 'GB')).toBe(1)
        })

        it('keeps user count when user exists in multiple buckets and one is pruned', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addGeoDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'US', 'user-1')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'US', 'user-1')

            expect(getCountryCount(window.getCountryBreakdown(), 'US')).toBe(1)

            tickMinute()

            window.addGeoDataPoint(toUnixSeconds(relativeTime(MINUTE)), 'US', 'user-2')
            window.prune()

            const breakdown = window.getCountryBreakdown()
            expect(getCountryCount(breakdown, 'US')).toBe(2)
        })

        it('returns empty array for empty window', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            expect(window.getCountryBreakdown()).toEqual([])
        })

        it('includes percentage and sorts by count descending', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'US', 'user-1')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'US', 'user-2')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'US', 'user-3')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'GB', 'user-4')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'GB', 'user-5')
            window.addGeoDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'DE', 'user-6')

            const breakdown = window.getCountryBreakdown()
            expect(breakdown).toHaveLength(3)
            expect(breakdown[0]).toEqual({ country: 'US', count: 3, percentage: 50 })
            expect(breakdown[1]).toEqual({ country: 'GB', count: 2, percentage: expect.closeTo(33.33, 1) })
            expect(breakdown[2]).toEqual({ country: 'DE', count: 1, percentage: expect.closeTo(16.67, 1) })
        })
    })

    describe('incremental totalPageviews', () => {
        it('tracks pageviews incrementally via addDataPoint', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 3 })
            expect(window.getTotalPageviews()).toBe(3)

            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-2', { pageviews: 7 })
            expect(window.getTotalPageviews()).toBe(10)
        })

        it('tracks pageviews incrementally via extendBucketData', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.extendBucketData(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                pageviews: 10,
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map(),
                browsers: new Map(),
                paths: new Map(),
                referrers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map<string, Set<string>>(),
            })

            expect(window.getTotalPageviews()).toBe(10)
        })

        it('decrements totalPageviews when buckets are pruned', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'user-1', { pageviews: 5 })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', { pageviews: 10 })

            expect(window.getTotalPageviews()).toBe(15)

            tickMinute()
            window.prune()

            expect(window.getTotalPageviews()).toBe(10)
        })
    })

    describe('incremental globalPathCounts', () => {
        it('tracks paths incrementally via addDataPoint', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 1, pathname: '/home' })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', { pageviews: 1, pathname: '/home' })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-3', {
                pageviews: 1,
                pathname: '/about',
            })

            const topPaths = window.getTopPaths(10)
            expect(topPaths).toEqual([
                { path: '/home', views: 2 },
                { path: '/about', views: 1 },
            ])
        })

        it('decrements path counts when buckets are pruned', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'user-1', {
                pageviews: 1,
                pathname: '/old-page',
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'user-2', {
                pageviews: 1,
                pathname: '/home',
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-3', {
                pageviews: 1,
                pathname: '/home',
            })

            expect(window.getTopPaths(10)).toEqual([
                { path: '/home', views: 2 },
                { path: '/old-page', views: 1 },
            ])

            tickMinute()
            window.prune()

            expect(window.getTopPaths(10)).toEqual([{ path: '/home', views: 1 }])
        })

        it('tracks paths incrementally via extendBucketData', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.extendBucketData(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                pageviews: 0,
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map(),
                browsers: new Map(),
                paths: new Map([
                    ['/home', 10],
                    ['/about', 5],
                ]),
                referrers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map<string, Set<string>>(),
            })

            expect(window.getTopPaths(10)).toEqual([
                { path: '/home', views: 10 },
                { path: '/about', views: 5 },
            ])
        })
    })

    describe('incremental new/returning user counts', () => {
        it('classifies first-time users as new', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', { pageviews: 1 })

            const buckets = window.getSortedBuckets()
            expect(buckets[0][1].newUserCount).toBe(2)
            expect(buckets[0][1].returningUserCount).toBe(0)
        })

        it('classifies users seen in earlier buckets as returning', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-1', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-2', { pageviews: 1 })

            const buckets = window.getSortedBuckets()
            expect(buckets[0][1].newUserCount).toBe(1)
            expect(buckets[0][1].returningUserCount).toBe(0)
            expect(buckets[1][1].newUserCount).toBe(1)
            expect(buckets[1][1].returningUserCount).toBe(1)
        })

        it('does not double-count duplicate users in same bucket', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 1 })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', { pageviews: 1 })

            const buckets = window.getSortedBuckets()
            expect(buckets[0][1].newUserCount).toBe(1)
            expect(buckets[0][1].returningUserCount).toBe(0)
            expect(buckets[0][1].uniqueUsers.size).toBe(1)
        })

        it('classifies users from extendBucketData correctly', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.extendBucketData(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                pageviews: 0,
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map(),
                browsers: new Map(),
                paths: new Map(),
                referrers: new Map(),
                uniqueUsers: new Set(['user-1', 'user-2']),
                countries: new Map<string, Set<string>>(),
            })

            window.extendBucketData(toUnixSeconds(relativeTime(-4 * MINUTE)), {
                pageviews: 0,
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map(),
                browsers: new Map(),
                paths: new Map(),
                referrers: new Map(),
                uniqueUsers: new Set(['user-1', 'user-3']),
                countries: new Map<string, Set<string>>(),
            })

            const buckets = window.getSortedBuckets()
            // user-1 and user-2 are new in the first bucket
            expect(buckets[0][1].newUserCount).toBe(2)
            expect(buckets[0][1].returningUserCount).toBe(0)
            // user-1 is returning, user-3 is new in the second bucket
            expect(buckets[1][1].newUserCount).toBe(1)
            expect(buckets[1][1].returningUserCount).toBe(1)
        })
    })

    describe('referrer tracking', () => {
        it('tracks referrers via addDataPoint', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', {
                pageviews: 1,
                referringDomain: 'google.com',
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', {
                pageviews: 1,
                referringDomain: 'google.com',
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-3', {
                pageviews: 1,
                referringDomain: 'twitter.com',
            })

            const topReferrers = window.getTopReferrers(10)
            expect(topReferrers).toEqual([
                { referrer: 'google.com', views: 2 },
                { referrer: 'twitter.com', views: 1 },
            ])
        })

        it('aggregates referrers across buckets', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', {
                pageviews: 1,
                referringDomain: 'google.com',
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-2', {
                pageviews: 1,
                referringDomain: 'google.com',
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-4 * MINUTE)), 'user-3', {
                pageviews: 1,
                referringDomain: '$direct',
            })

            const topReferrers = window.getTopReferrers(10)
            expect(topReferrers).toEqual([
                { referrer: 'google.com', views: 2 },
                { referrer: '$direct', views: 1 },
            ])
        })

        it('respects limit parameter', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-1', {
                pageviews: 1,
                referringDomain: 'google.com',
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', {
                pageviews: 1,
                referringDomain: 'twitter.com',
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-3', {
                pageviews: 1,
                referringDomain: 'facebook.com',
            })

            const topReferrers = window.getTopReferrers(2)
            expect(topReferrers).toHaveLength(2)
        })

        it('decrements referrer counts when buckets are pruned', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.addDataPoint(toUnixSeconds(relativeTime(-30 * MINUTE)), 'user-1', {
                pageviews: 1,
                referringDomain: 'old-referrer.com',
            })
            window.addDataPoint(toUnixSeconds(relativeTime(-5 * MINUTE)), 'user-2', {
                pageviews: 1,
                referringDomain: 'google.com',
            })

            expect(window.getTopReferrers(10)).toHaveLength(2)

            tickMinute()
            window.prune()

            const topReferrers = window.getTopReferrers(10)
            expect(topReferrers).toEqual([{ referrer: 'google.com', views: 1 }])
        })

        it('tracks referrers via extendBucketData', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)

            window.extendBucketData(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                pageviews: 0,
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map(),
                paths: new Map(),
                referrers: new Map([
                    ['google.com', 10],
                    ['$direct', 5],
                ]),
                browsers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map<string, Set<string>>(),
            })

            expect(window.getTopReferrers(10)).toEqual([
                { referrer: 'google.com', views: 10 },
                { referrer: '$direct', views: 5 },
            ])
        })

        it('returns empty array for empty window', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            expect(window.getTopReferrers(10)).toEqual([])
        })
    })

    describe('bot tracking', () => {
        it('tracks bot counts per name via addDataPoint', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const eventTs = toUnixSeconds(relativeTime(-5 * MINUTE))

            window.addDataPoint(eventTs, 'bot-1', { bot: { name: 'Googlebot', category: 'Search crawler' } })
            window.addDataPoint(eventTs, 'bot-2', { bot: { name: 'Googlebot', category: 'Search crawler' } })
            window.addDataPoint(eventTs, 'bot-3', { bot: { name: 'GPTBot', category: 'AI crawler' } })

            expect(window.getTotalBotEvents()).toBe(3)
            expect(window.getBotBreakdown()).toEqual([
                { bot: 'Googlebot', category: 'Search crawler', count: 2, percentage: (2 / 3) * 100 },
                { bot: 'GPTBot', category: 'AI crawler', count: 1, percentage: (1 / 3) * 100 },
            ])
        })

        it('rolls excess bots into the "Other" bucket when over the limit', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const eventTs = toUnixSeconds(relativeTime(-5 * MINUTE))

            window.addDataPoint(eventTs, 'a', { bot: { name: 'Googlebot', category: 'Search crawler' } })
            window.addDataPoint(eventTs, 'b', { bot: { name: 'GPTBot', category: 'AI crawler' } })
            window.addDataPoint(eventTs, 'c', { bot: { name: 'Bingbot', category: 'Search crawler' } })

            const breakdown = window.getBotBreakdown(2)
            expect(breakdown.length).toBe(3)
            expect(breakdown[2].bot).toBe('Other')
            expect(breakdown[2].count).toBe(1)
        })

        it('decrements bot counts when buckets are pruned', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            const oldTs = toUnixSeconds(relativeTime(-40 * MINUTE))
            const recentTs = toUnixSeconds(relativeTime(-5 * MINUTE))

            window.addDataPoint(oldTs, 'old-1', { bot: { name: 'ClaudeBot', category: 'AI crawler' } })
            window.addDataPoint(recentTs, 'new-1', { bot: { name: 'Googlebot', category: 'Search crawler' } })

            window.prune()

            expect(window.getTotalBotEvents()).toBe(1)
            expect(window.getBotBreakdown().map((b) => b.bot)).toEqual(['Googlebot'])
        })

        it('round-trips bot data through extendBucketData', () => {
            const window = new LiveMetricsSlidingWindow(WINDOW_SIZE_MINUTES)
            window.extendBucketData(toUnixSeconds(relativeTime(-5 * MINUTE)), {
                pageviews: 0,
                newUserCount: 0,
                returningUserCount: 0,
                devices: new Map(),
                paths: new Map(),
                referrers: new Map(),
                browsers: new Map(),
                uniqueUsers: new Set(),
                countries: new Map(),
                bots: new Map([
                    ['Googlebot', { count: 4, category: 'Search crawler' }],
                    ['GPTBot', { count: 2, category: 'AI crawler' }],
                ]),
            })

            expect(window.getTotalBotEvents()).toBe(6)
            expect(window.getBotBreakdown().map((b) => b.bot)).toEqual(['Googlebot', 'GPTBot'])
        })
    })
})
