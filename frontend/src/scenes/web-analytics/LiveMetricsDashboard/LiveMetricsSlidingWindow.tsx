import { SlidingWindowBucket } from './LiveWebAnalyticsMetricsTypes'

export class LiveMetricsSlidingWindow {
    private buckets = new Map<number, SlidingWindowBucket>()
    private windowSizeSeconds: number

    constructor(windowSizeMinutes: number) {
        this.windowSizeSeconds = windowSizeMinutes * 60
    }

    addDataPoint(
        eventTs: number,
        distinctId: string,
        data: {
            pageviews: number | undefined
            pathname: string | undefined
            device: { deviceId: string; deviceType: string } | undefined
        }
    ): void {
        const bucket = this.getOrCreateBucket(eventTs)

        bucket.uniqueUsers.add(distinctId)

        if (data.pageviews) {
            bucket.pageviews += data.pageviews
        }

        if (data.pathname) {
            bucket.paths.set(data.pathname, (bucket.paths.get(data.pathname) || 0) + 1)
        }

        if (data.device) {
            const existingDeviceIds = bucket.devices.get(data.device.deviceType) ?? new Set<string>()

            existingDeviceIds.add(data.device.deviceId)
            bucket.devices.set(data.device.deviceType, existingDeviceIds)
        }

        this.prune()
    }

    extendBucketData(eventTs: number, data: SlidingWindowBucket): void {
        const bucket = this.getOrCreateBucket(eventTs)

        if (data.uniqueUsers) {
            for (const distinctId of data.uniqueUsers) {
                bucket.uniqueUsers.add(distinctId)
            }
        }

        if (data.pageviews) {
            bucket.pageviews += data.pageviews
        }

        if (data.devices) {
            for (const [deviceType, deviceIds] of data.devices) {
                const existingDeviceIds: Set<string> = bucket.devices.get(deviceType) ?? new Set<string>()

                for (const deviceId of deviceIds) {
                    existingDeviceIds.add(deviceId)
                }

                bucket.devices.set(deviceType, existingDeviceIds)
            }
        }

        if (data.paths) {
            for (const [path, count] of data.paths) {
                bucket.paths.set(path, (bucket.paths.get(path) || 0) + count)
            }
        }

        this.prune()
    }

    private prune(): void {
        const nowTs = Date.now() / 1000
        const threshold = nowTs - this.windowSizeSeconds
        for (const ts of this.buckets.keys()) {
            if (ts < threshold) {
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

    getDeviceTotals(): Map<string, number> {
        const allDeviceIds = new Map<string, Set<string>>()

        for (const bucket of this.buckets.values()) {
            for (const [deviceType, deviceIds] of bucket.devices) {
                const existingIds = allDeviceIds.get(deviceType) ?? new Set<string>()
                for (const id of deviceIds) {
                    existingIds.add(id)
                }
                allDeviceIds.set(deviceType, existingIds)
            }
        }

        const deviceTotals = new Map<string, number>()
        for (const [deviceType, deviceIds] of allDeviceIds) {
            deviceTotals.set(deviceType, deviceIds.size)
        }

        return deviceTotals
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

    private getOrCreateBucket(eventTs: number): SlidingWindowBucket {
        const bucketTs = Math.floor(eventTs / 60) * 60

        let bucket = this.buckets.get(bucketTs)

        if (!bucket) {
            bucket = {
                pageviews: 0,
                devices: new Map<string, Set<string>>(),
                paths: new Map<string, number>(),
                uniqueUsers: new Set<string>(),
            }
            this.buckets.set(bucketTs, bucket)
        }

        return bucket
    }
}
