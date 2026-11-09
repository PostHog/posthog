type Bucket = [tokens: number, lastReplenishedTimestamp: number, lastConsumedSweep: number]

// Max entries in a javascript Map is 2^24 or 16777216
const DEFAULT_MAX_BUCKETS = 10000000

const MIN_SWEEP_INTERVAL_MS = 1000

export class MemoryRateLimiter {
    public buckets: Map<string, Bucket>
    public replenishRate: number
    public bucketCapacity: number
    public maxBuckets: number

    private refillWindowMs: number
    private sweepIntervalMs: number
    private latestTimestamp: number = 0
    private nextSweepAt: number = 0
    private sweepCount: number = 0

    constructor(bucketCapacity: number, replenishRate: number, maxBuckets: number = DEFAULT_MAX_BUCKETS) {
        this.buckets = new Map()
        this.bucketCapacity = bucketCapacity
        this.replenishRate = replenishRate
        this.maxBuckets = maxBuckets
        this.refillWindowMs = (bucketCapacity / replenishRate) * 1000
        // A tiny window would scan every bucket on every call.
        this.sweepIntervalMs = this.refillWindowMs > MIN_SWEEP_INTERVAL_MS ? this.refillWindowMs : MIN_SWEEP_INTERVAL_MS
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

    /**
     * Removes buckets that are full again: a full bucket gives the same decision as a new one.
     * Runs at most once per refill window, so the caller can pass the clock once per batch.
     *
     * Bucket timestamps are event time, so a bucket counts as full only when the newest event time
     * is one refill window past it and the bucket saw no consume since the previous sweep, which is
     * at least one refill window of wall clock ago. A stopped consumer or a lagging partition must
     * not reset buckets that are still draining.
     */
    sweepRefilled(wallNow: number): void {
        if (wallNow < this.nextSweepAt) {
            return
        }
        this.nextSweepAt = wallNow + this.sweepIntervalMs
        for (const [key, bucket] of this.buckets) {
            if (bucket[2] < this.sweepCount && this.latestTimestamp - bucket[1] >= this.refillWindowMs) {
                this.buckets.delete(key)
            }
        }
        this.sweepCount++
    }
}
