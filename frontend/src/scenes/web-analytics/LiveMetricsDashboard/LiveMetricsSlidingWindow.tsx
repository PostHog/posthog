import { SlidingWindowBucket } from './LiveWebAnalyticsMetricsTypes'

export class LiveMetricsSlidingWindow {
    private buckets = new Map<number, SlidingWindowBucket>()
    private windowSizeSeconds: number

    constructor(windowSizeMinutes: number) {
        this.windowSizeSeconds = windowSizeMinutes * 60
    }

    addDataPoint(
        eventTs: number,
        data: Partial<SlidingWindowBucket> & { distinctId?: string; distinctIds?: string[] }
    ): void {
        const bucketTs = Math.floor(eventTs / 60) * 60
        const bucket = this.buckets.get(bucketTs) ?? {
            pageviews: 0,
            devices: new Map(),
            paths: new Map(),
            uniqueUsers: new Set(),
        }

        if (data.pageviews) {
            bucket.pageviews += data.pageviews
        }

        if (data.devices) {
            for (const [device, count] of data.devices) {
                bucket.devices.set(device, (bucket.devices.get(device) || 0) + count)
            }
        }

        if (data.paths) {
            for (const [path, count] of data.paths) {
                bucket.paths.set(path, (bucket.paths.get(path) || 0) + count)
            }
        }
        if (data.uniqueUsers) {
            for (const id of data.uniqueUsers) {
                bucket.uniqueUsers.add(id)
            }
        }
        if (data.distinctId) {
            bucket.uniqueUsers.add(data.distinctId)
        }
        if (data.distinctIds) {
            for (const id of data.distinctIds) {
                bucket.uniqueUsers.add(id)
            }
        }

        this.buckets.set(bucketTs, bucket)
        this.prune(eventTs)
    }

    private prune(nowTs: number): void {
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
        const deviceTotals = new Map<string, number>()

        for (const bucket of this.buckets.values()) {
            for (const [device, count] of bucket.devices) {
                const current = deviceTotals.get(device) ?? 0
                deviceTotals.set(device, current + count)
            }
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
}
