type Bucket = [tokens: number, lastReplenishedTimestamp: number]

export class MemoryRateLimiter {
    public buckets: Map<string, Bucket>
    public replenishRate: number
    public bucketCapacity: number

    constructor(bucketCapacity: number, replenishRate: number) {
        this.buckets = new Map()
        this.bucketCapacity = bucketCapacity
        this.replenishRate = replenishRate
    }

    private getBucket(key: string): Bucket {
        let bucket = this.buckets.get(key)
        if (bucket === undefined) {
            bucket = [this.bucketCapacity, Date.now()]
            this.buckets.set(key, bucket)
        }
        return bucket
    }

    private replenish(bucket: Bucket, now?: number): void {
        const replenish_timestamp: number = now ?? Date.now()

        // Replenish the bucket if replenish_timestamp is higher than lastReplenishedTimestamp
        const secondsToReplenish = (replenish_timestamp - bucket[1]) / 1000
        if (secondsToReplenish > 0) {
            bucket[0] += this.replenishRate * secondsToReplenish
            bucket[0] = Math.min(bucket[0], this.bucketCapacity)
            bucket[1] = replenish_timestamp
        }
    }

    consume(key: string, tokens: number, now?: number): boolean {
        const bucket = this.getBucket(key)
        this.replenish(bucket, now)

        bucket[0] -= tokens

        if (bucket[0] < 0) {
            return false
        }

        return true
    }
}
