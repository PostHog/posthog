type Bucket = [tokens: number, lastReplenishedTimestamp: number, lastConsumedAtMs: number]

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
    private nextSweepAt: number

    constructor(bucketCapacity: number, replenishRate: number, maxBuckets: number = DEFAULT_MAX_BUCKETS) {
        this.buckets = new Map()
        this.bucketCapacity = bucketCapacity
        this.replenishRate = replenishRate
        this.maxBuckets = maxBuckets
        this.refillWindowMs = (bucketCapacity / replenishRate) * 1000
        // A tiny window would scan every bucket on every call.
        this.sweepIntervalMs = this.refillWindowMs > MIN_SWEEP_INTERVAL_MS ? this.refillWindowMs : MIN_SWEEP_INTERVAL_MS
        this.nextSweepAt = Date.now() + this.sweepIntervalMs
    }

    private getBucket(key: string, now: number, wallNow: number): Bucket {
        let bucket = this.buckets.get(key)
        if (bucket === undefined) {
            // If we're at capacity, just remove the first key (oldest insertion)
            if (this.buckets.size >= this.maxBuckets) {
                const firstKey = this.buckets.keys().next().value
                if (firstKey) {
                    this.buckets.delete(firstKey)
                }
            }
            bucket = [this.bucketCapacity, now, wallNow]
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
        const wallNow = Date.now()
        const timestamp = now ?? wallNow
        this.latestTimestamp = Math.max(this.latestTimestamp, timestamp)
        this.sweepRefilled(wallNow)

        const bucket = this.getBucket(key, timestamp, wallNow)
        this.replenish(bucket, timestamp)
        bucket[2] = wallNow

        bucket[0] -= tokens

        if (bucket[0] < 0) {
            return false
        }

        return true
    }

    /**
     * A full bucket gives the same decision as a new one. Bucket timestamps are event time, so a
     * bucket counts as full only when both the newest event time and the wall clock since its
     * last consume are one refill window past it: a stopped consumer or a lagging partition
     * must not reset buckets that are still draining.
     */
    private sweepRefilled(now: number): void {
        if (now < this.nextSweepAt) {
            return
        }
        this.nextSweepAt = now + this.sweepIntervalMs
        for (const [key, bucket] of this.buckets) {
            if (this.latestTimestamp - bucket[1] >= this.refillWindowMs && now - bucket[2] >= this.refillWindowMs) {
                this.buckets.delete(key)
            }
        }
    }
}
