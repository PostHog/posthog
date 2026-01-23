import { CountryBreakdownItem, SlidingWindowBucket } from './LiveWebAnalyticsMetricsTypes'

export class LiveMetricsSlidingWindow {
    private buckets = new Map<number, SlidingWindowBucket>()
    private windowSizeSeconds: number
    // Tracks how many buckets each user appears in for efficient total unique user counting
    private userBucketCounts = new Map<string, number>()
    // Tracks how many buckets each device appears in, per device type
    private deviceBucketCounts = new Map<string, Map<string, number>>()

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

        this.prune()
    }

    addGeoDataPoint(eventTs: number, countryCode: string, count: number = 1): void {
        if (!countryCode) {
            return
        }
        const bucket = this.getOrCreateBucket(eventTs)
        bucket.countries.set(countryCode, (bucket.countries.get(countryCode) || 0) + count)
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

        if (data.paths) {
            for (const [path, count] of data.paths) {
                bucket.paths.set(path, (bucket.paths.get(path) || 0) + count)
            }
        }

        if (data.countries) {
            for (const [country, count] of data.countries) {
                bucket.countries.set(country, (bucket.countries.get(country) || 0) + count)
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

    private addDeviceToBucket(bucket: SlidingWindowBucket, deviceType: string, deviceId: string): void {
        const bucketDeviceIds = bucket.devices.get(deviceType) ?? new Set<string>()

        if (!bucketDeviceIds.has(deviceId)) {
            bucketDeviceIds.add(deviceId)
            bucket.devices.set(deviceType, bucketDeviceIds)

            // Update global tracking
            const deviceTypeCounts = this.deviceBucketCounts.get(deviceType) ?? new Map<string, number>()
            deviceTypeCounts.set(deviceId, (deviceTypeCounts.get(deviceId) || 0) + 1)
            this.deviceBucketCounts.set(deviceType, deviceTypeCounts)
        }
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

    private removeDevicesFromTracking(bucket: SlidingWindowBucket): void {
        for (const [deviceType, deviceIds] of bucket.devices) {
            const deviceTypeCounts = this.deviceBucketCounts.get(deviceType)
            if (!deviceTypeCounts) {
                continue
            }

            for (const deviceId of deviceIds) {
                const count = deviceTypeCounts.get(deviceId) || 0
                if (count <= 1) {
                    deviceTypeCounts.delete(deviceId)
                } else {
                    deviceTypeCounts.set(deviceId, count - 1)
                }
            }

            // Clean up empty device type maps
            if (deviceTypeCounts.size === 0) {
                this.deviceBucketCounts.delete(deviceType)
            }
        }
    }

    private prune(): void {
        const nowTs = Date.now() / 1000
        const threshold = nowTs - this.windowSizeSeconds
        for (const [ts, bucket] of this.buckets.entries()) {
            if (ts < threshold) {
                this.removeUsersFromTracking(bucket)
                this.removeDevicesFromTracking(bucket)
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

    getTotalDeviceCount(): number {
        let total = 0
        for (const deviceIdCounts of this.deviceBucketCounts.values()) {
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

    getCountryBreakdown(): CountryBreakdownItem[] {
        const aggregates = new Map<string, number>()
        let total = 0

        for (const bucket of this.buckets.values()) {
            for (const [country, count] of bucket.countries) {
                aggregates.set(country, (aggregates.get(country) || 0) + count)
                total += count
            }
        }

        if (total === 0) {
            return []
        }

        return [...aggregates.entries()]
            .map(([country, count]) => ({
                country,
                count,
                percentage: (count / total) * 100,
            }))
            .sort((a, b) => b.count - a.count)
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
                paths: new Map<string, number>(),
                uniqueUsers: new Set<string>(),
                countries: new Map<string, number>(),
            }
            this.buckets.set(bucketTs, bucket)
        }

        return bucket
    }
}
