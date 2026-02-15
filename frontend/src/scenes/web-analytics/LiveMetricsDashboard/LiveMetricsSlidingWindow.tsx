import { BrowserBreakdownItem, SlidingWindowBucket } from './LiveWebAnalyticsMetricsTypes'

export class LiveMetricsSlidingWindow {
    private buckets = new Map<number, SlidingWindowBucket>()
    private windowSizeSeconds: number

    // Tracks how many buckets each entity appears in
    private userBucketCounts = new Map<string, number>()
    private deviceBucketCounts = new Map<string, Map<string, number>>()
    private browserBucketCounts = new Map<string, Map<string, number>>()

    constructor(windowSizeMinutes: number) {
        this.windowSizeSeconds = windowSizeMinutes * 60
    }

    addDataPoint(
        eventTs: number,
        distinctId: string,
        data: {
            pageviews?: number
            pathname?: string
            device?: { deviceId: string; deviceType: string }
            browser?: { deviceId: string; browserType: string }
        }
    ): void {
        const bucket = this.getOrCreateBucket(eventTs)

        this.addUserToBucket(bucket, distinctId)

        if (data.pageviews) {
            bucket.pageviews += data.pageviews
        }

        if (data.pathname) {
            bucket.paths.set(data.pathname, (bucket.paths.get(data.pathname) || 0) + 1)
        }

        if (data.device) {
            this.addDeviceToBucket(bucket, data.device.deviceType, data.device.deviceId)
        }

        if (data.browser) {
            this.addBrowserToBucket(bucket, data.browser.browserType, data.browser.deviceId)
        }

        this.prune()
    }

    extendBucketData(eventTs: number, data: SlidingWindowBucket): void {
        const bucket = this.getOrCreateBucket(eventTs)

        if (data.uniqueUsers) {
            for (const distinctId of data.uniqueUsers) {
                this.addUserToBucket(bucket, distinctId)
            }
        }

        if (data.pageviews) {
            bucket.pageviews += data.pageviews
        }

        if (data.devices) {
            for (const [deviceType, deviceIds] of data.devices) {
                for (const deviceId of deviceIds) {
                    this.addDeviceToBucket(bucket, deviceType, deviceId)
                }
            }
        }

        if (data.browsers) {
            for (const [browserType, deviceIds] of data.browsers) {
                for (const deviceId of deviceIds) {
                    this.addBrowserToBucket(bucket, browserType, deviceId)
                }
            }
        }

        if (data.paths) {
            for (const [path, count] of data.paths) {
                bucket.paths.set(path, (bucket.paths.get(path) || 0) + count)
            }
        }

        this.prune()
    }

    private addUserToBucket(bucket: SlidingWindowBucket, userId: string): void {
        if (!bucket.uniqueUsers.has(userId)) {
            bucket.uniqueUsers.add(userId)
            this.userBucketCounts.set(userId, (this.userBucketCounts.get(userId) || 0) + 1)
        }
    }

    private addItemToBucket(
        bucketMap: Map<string, Set<string>>,
        globalCounts: Map<string, Map<string, number>>,
        itemType: string,
        itemId: string
    ): void {
        const bucketIds = bucketMap.get(itemType) ?? new Set<string>()

        if (!bucketIds.has(itemId)) {
            bucketIds.add(itemId)
            bucketMap.set(itemType, bucketIds)

            const typeCounts = globalCounts.get(itemType) ?? new Map<string, number>()
            typeCounts.set(itemId, (typeCounts.get(itemId) || 0) + 1)
            globalCounts.set(itemType, typeCounts)
        }
    }

    private addDeviceToBucket(bucket: SlidingWindowBucket, deviceType: string, deviceId: string): void {
        this.addItemToBucket(bucket.devices, this.deviceBucketCounts, deviceType, deviceId)
    }

    private addBrowserToBucket(bucket: SlidingWindowBucket, browserType: string, deviceId: string): void {
        this.addItemToBucket(bucket.browsers, this.browserBucketCounts, browserType, deviceId)
    }

    private removeUsersFromTracking(bucket: SlidingWindowBucket): void {
        for (const userId of bucket.uniqueUsers) {
            const count = this.userBucketCounts.get(userId) || 0
            if (count <= 1) {
                this.userBucketCounts.delete(userId)
            } else {
                this.userBucketCounts.set(userId, count - 1)
            }
        }
    }

    private removeItemsFromTracking(
        bucketMap: Map<string, Set<string>>,
        globalCounts: Map<string, Map<string, number>>
    ): void {
        for (const [itemType, itemIds] of bucketMap) {
            const typeCounts = globalCounts.get(itemType)
            if (!typeCounts) {
                continue
            }

            for (const itemId of itemIds) {
                const count = typeCounts.get(itemId) || 0
                if (count <= 1) {
                    typeCounts.delete(itemId)
                } else {
                    typeCounts.set(itemId, count - 1)
                }
            }

            if (typeCounts.size === 0) {
                globalCounts.delete(itemType)
            }
        }
    }

    private prune(): void {
        const nowTs = Date.now() / 1000
        const threshold = nowTs - this.windowSizeSeconds
        for (const [ts, bucket] of this.buckets.entries()) {
            if (ts < threshold) {
                this.removeUsersFromTracking(bucket)
                this.removeItemsFromTracking(bucket.devices, this.deviceBucketCounts)
                this.removeItemsFromTracking(bucket.browsers, this.browserBucketCounts)
                this.buckets.delete(ts)
            }
        }
    }

    getSortedBuckets(): [number, SlidingWindowBucket][] {
        return [...this.buckets.entries()].sort(([a], [b]) => a - b)
    }

    getTotalPageviews(): number {
        let total = 0
        for (const bucket of this.buckets.values()) {
            total += bucket.pageviews
        }
        return total
    }

    getDeviceBreakdown(): { device: string; count: number; percentage: number }[] {
        let total = 0
        const counts: { device: string; count: number }[] = []

        for (const [deviceType, deviceIdCounts] of this.deviceBucketCounts) {
            const count = deviceIdCounts.size
            total += count
            counts.push({ device: deviceType, count })
        }

        if (total === 0) {
            return []
        }

        return counts
            .map(({ device, count }) => ({
                device,
                count,
                percentage: (count / total) * 100,
            }))
            .sort((a, b) => b.count - a.count)
    }

    getBrowserBreakdown(limit?: number): BrowserBreakdownItem[] {
        let total = 0
        const counts: { browser: string; count: number }[] = []

        for (const [browserType, deviceIdCounts] of this.browserBucketCounts) {
            const count = deviceIdCounts.size
            total += count
            counts.push({ browser: browserType, count })
        }

        if (total === 0) {
            return []
        }

        const sorted = counts
            .map(({ browser, count }) => ({
                browser,
                count,
                percentage: (count / total) * 100,
            }))
            .sort((a, b) => b.count - a.count)

        if (!limit || sorted.length <= limit) {
            return sorted
        }

        const top = sorted.slice(0, limit)
        const othersCount = sorted.slice(limit).reduce((sum, item) => sum + item.count, 0)

        if (othersCount > 0) {
            top.push({
                browser: 'Other',
                count: othersCount,
                percentage: (othersCount / total) * 100,
            })
        }

        return top
    }

    getTotalBrowsers(): number {
        let total = 0
        for (const deviceIdCounts of this.browserBucketCounts.values()) {
            total += deviceIdCounts.size
        }
        return total
    }

    getTopPaths(limit: number): { path: string; views: number }[] {
        const aggregates = new Map<string, number>()
        for (const bucket of this.buckets.values()) {
            for (const [path, count] of bucket.paths) {
                aggregates.set(path, (aggregates.get(path) || 0) + count)
            }
        }
        return [...aggregates.entries()]
            .map(([path, views]) => ({ path, views }))
            .sort((a, b) => b.views - a.views)
            .slice(0, limit)
    }

    getTotalUniqueUsers(): number {
        return this.userBucketCounts.size
    }

    private getOrCreateBucket(eventTs: number): SlidingWindowBucket {
        const bucketTs = Math.floor(eventTs / 60) * 60

        let bucket = this.buckets.get(bucketTs)

        if (!bucket) {
            bucket = {
                pageviews: 0,
                devices: new Map<string, Set<string>>(),
                browsers: new Map<string, Set<string>>(),
                paths: new Map<string, number>(),
                uniqueUsers: new Set<string>(),
            }
            this.buckets.set(bucketTs, bucket)
        }

        return bucket
    }
}
