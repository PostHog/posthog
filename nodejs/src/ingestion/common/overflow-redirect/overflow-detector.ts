type Bucket = [tokens: number, lastReplenishedTimestamp: number, lastConsumedSweep: number]

// Max entries in a javascript Map is 2^24 or 16777216
const DEFAULT_MAX_BUCKETS = 10000000

const MIN_SWEEP_INTERVAL_MS = 1000

export class MemoryRateLimiter {
    public buckets: Map<string, Bucket>
    public replenishRate: number
    public bucketCapacity: number
    public maxBuckets: number

    private sweepIntervalMs: number
    private latestTimestamp: number = 0
    private nextSweepAt: number = 0
    private sweepCount: number = 0

    constructor(bucketCapacity: number, replenishRate: number, maxBuckets: number = DEFAULT_MAX_BUCKETS) {
        this.buckets = new Map()
        this.bucketCapacity = bucketCapacity
        this.replenishRate = replenishRate
        this.maxBuckets = maxBuckets
        const refillWindowMs = (bucketCapacity / replenishRate) * 1000
        this.sweepIntervalMs = refillWindowMs > MIN_SWEEP_INTERVAL_MS ? refillWindowMs : MIN_SWEEP_INTERVAL_MS
    }

    private getBucket(key: string, now: number): Bucket {
        let bucket = this.buckets.get(key)
        if (bucket === undefined) {
            // If we're at capacity, just remove the first key (oldest insertion)
            if (this.buckets.size >= this.maxBuckets) {
                const firstKey = this.buckets.keys().next().value
                if (firstKey) {
                    this.buckets.delete(firstKey)
                }
            }
            bucket = [this.bucketCapacity, now, this.sweepCount]
            this.buckets.set(key, bucket)
        }
        return bucket
    }

    private replenish(bucket: Bucket, now: number): void {
        const secondsToReplenish = (now - bucket[1]) / 1000
        if (secondsToReplenish > 0) {
            bucket[0] += this.replenishRate * secondsToReplenish
            bucket[0] = Math.min(bucket[0], this.bucketCapacity)
            bucket[1] = now
        }
    }

    consume(key: string, tokens: number, now?: number): boolean {
        const timestamp = now ?? Date.now()
        if (timestamp > this.latestTimestamp) {
            this.latestTimestamp = timestamp
        }

        const bucket = this.getBucket(key, timestamp)
        this.replenish(bucket, timestamp)
        bucket[2] = this.sweepCount

        bucket[0] -= tokens

        if (bucket[0] < 0) {
            return false
        }

        return true
    }

    removeRefilledBuckets(wallNow: number): void {
        if (wallNow < this.nextSweepAt) {
            return
        }
        this.nextSweepAt = wallNow + this.sweepIntervalMs
        for (const [key, bucket] of this.buckets) {
            const refilledInEventTime =
                bucket[0] + (this.replenishRate * (this.latestTimestamp - bucket[1])) / 1000 >= this.bucketCapacity
            const idleSincePreviousSweep = bucket[2] < this.sweepCount
            if (refilledInEventTime && idleSincePreviousSweep) {
                this.buckets.delete(key)
            }
        }
        this.sweepCount++
    }
}
