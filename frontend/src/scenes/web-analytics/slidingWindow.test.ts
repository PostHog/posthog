import { LiveMetricsSlidingWindow } from './LiveMetricsDashboard/LiveMetricsSlidingWindow'

describe('LiveMetricsSlidingWindow', () => {
    describe('getSortedBuckets', () => {
        it('returns buckets in chronological order', () => {
            const window = new LiveMetricsSlidingWindow(30)
            const baseTs = 1000000

            // Add events in random order
            window.addDataPoint(baseTs + 120, { pageviews: 1 })
            window.addDataPoint(baseTs, { pageviews: 1 })
            window.addDataPoint(baseTs + 60, { pageviews: 1 })

            const buckets = window.getSortedBuckets()
            expect(buckets.length).toBe(3)
            expect(buckets[0][0]).toBe(Math.floor(baseTs / 60) * 60)
            expect(buckets[1][0]).toBe(Math.floor((baseTs + 60) / 60) * 60)
            expect(buckets[2][0]).toBe(Math.floor((baseTs + 120) / 60) * 60)
        })

        it('returns empty array for empty window', () => {
            const window = new LiveMetricsSlidingWindow(30)
            expect(window.getSortedBuckets()).toEqual([])
        })
    })

    describe('getTotalPageviews', () => {
        it('sums pageviews across all buckets', () => {
            const window = new LiveMetricsSlidingWindow(30)
            const baseTs = 1000000

            window.addDataPoint(baseTs, { pageviews: 5 })
            window.addDataPoint(baseTs + 60, { pageviews: 10 })
            window.addDataPoint(baseTs + 120, { pageviews: 15 })

            expect(window.getTotalPageviews()).toBe(30)
        })

        it('returns 0 for empty window', () => {
            const window = new LiveMetricsSlidingWindow(30)
            expect(window.getTotalPageviews()).toBe(0)
        })
    })

    describe('getDeviceTotals', () => {
        it('aggregates device counts across buckets', () => {
            const window = new LiveMetricsSlidingWindow(30)
            const baseTs = 1000000

            window.addDataPoint(baseTs, {
                devices: new Map([
                    ['Mobile', 5],
                    ['Desktop', 10],
                ]),
            })
            window.addDataPoint(baseTs + 60, {
                devices: new Map([
                    ['Mobile', 3],
                    ['Desktop', 7],
                ]),
            })

            const totals = window.getDeviceTotals()
            expect(totals.get('Mobile')).toBe(8)
            expect(totals.get('Desktop')).toBe(17)
        })

        it('returns empty map for empty window', () => {
            const window = new LiveMetricsSlidingWindow(30)
            const totals = window.getDeviceTotals()
            expect(totals.size).toBe(0)
        })
    })

    describe('getTopPaths', () => {
        it('returns top N paths sorted by views', () => {
            const window = new LiveMetricsSlidingWindow(30)
            const baseTs = 1000000

            window.addDataPoint(baseTs, {
                paths: new Map([
                    ['/a', 10],
                    ['/b', 5],
                    ['/c', 20],
                ]),
            })
            window.addDataPoint(baseTs + 60, {
                paths: new Map([
                    ['/a', 5],
                    ['/d', 3],
                ]),
            })

            const topPaths = window.getTopPaths(3)
            expect(topPaths).toEqual([
                { path: '/c', views: 20 },
                { path: '/a', views: 15 },
                { path: '/b', views: 5 },
            ])
        })

        it('limits results to requested count', () => {
            const window = new LiveMetricsSlidingWindow(30)
            const baseTs = 1000000

            window.addDataPoint(baseTs, {
                paths: new Map([
                    ['/a', 10],
                    ['/b', 9],
                    ['/c', 8],
                    ['/d', 7],
                    ['/e', 6],
                ]),
            })

            const topPaths = window.getTopPaths(2)
            expect(topPaths.length).toBe(2)
            expect(topPaths[0].path).toBe('/a')
            expect(topPaths[1].path).toBe('/b')
        })

        it('returns empty array for empty window', () => {
            const window = new LiveMetricsSlidingWindow(30)
            expect(window.getTopPaths(10)).toEqual([])
        })
    })

    describe('uniqueUsers', () => {
        it('deduplicates distinct_ids within same bucket', () => {
            const window = new LiveMetricsSlidingWindow(30)
            // Use a timestamp clearly in the middle of a minute
            const baseTs = 1000030

            window.addDataPoint(baseTs, { distinctId: 'user-1' })
            window.addDataPoint(baseTs + 5, { distinctId: 'user-1' })
            window.addDataPoint(baseTs + 10, { distinctId: 'user-2' })

            const buckets = window.getSortedBuckets()
            expect(buckets.length).toBe(1)
            expect(buckets[0][1].uniqueUsers.size).toBe(2)
        })

        it('handles distinctIds array', () => {
            const window = new LiveMetricsSlidingWindow(30)
            const baseTs = 1000000

            window.addDataPoint(baseTs, { distinctIds: ['user-1', 'user-2', 'user-1'] })

            const buckets = window.getSortedBuckets()
            expect(buckets[0][1].uniqueUsers.size).toBe(2)
        })
    })

    describe('pruning', () => {
        it('removes buckets older than window size', () => {
            const window = new LiveMetricsSlidingWindow(5) // 5 minute window
            const baseTs = 1000000

            // Add event at current time
            window.addDataPoint(baseTs, { pageviews: 1 })

            // Add event 6 minutes later - should prune the first one
            window.addDataPoint(baseTs + 6 * 60, { pageviews: 1 })

            const buckets = window.getSortedBuckets()
            expect(buckets.length).toBe(1)
            expect(buckets[0][0]).toBe(Math.floor((baseTs + 6 * 60) / 60) * 60)
        })

        it('keeps buckets within window size', () => {
            const window = new LiveMetricsSlidingWindow(5) // 5 minute window
            const baseTs = 1000000

            // Add events across 5 minutes
            for (let i = 0; i < 5; i++) {
                window.addDataPoint(baseTs + i * 60, { pageviews: 1 })
            }

            expect(window.getSortedBuckets().length).toBe(5)
        })
    })

    describe('edge cases', () => {
        it('handles single event', () => {
            const window = new LiveMetricsSlidingWindow(30)
            window.addDataPoint(1000000, { pageviews: 1, distinctId: 'user-1' })

            expect(window.getTotalPageviews()).toBe(1)
            expect(window.getSortedBuckets().length).toBe(1)
        })

        it('handles multiple events at exact same timestamp', () => {
            const window = new LiveMetricsSlidingWindow(30)
            const ts = 1000000

            window.addDataPoint(ts, { pageviews: 1, distinctId: 'user-1' })
            window.addDataPoint(ts, { pageviews: 1, distinctId: 'user-2' })
            window.addDataPoint(ts, { pageviews: 1, distinctId: 'user-1' })

            const buckets = window.getSortedBuckets()
            expect(buckets.length).toBe(1)
            expect(buckets[0][1].pageviews).toBe(3)
            expect(buckets[0][1].uniqueUsers.size).toBe(2)
        })
    })
})
