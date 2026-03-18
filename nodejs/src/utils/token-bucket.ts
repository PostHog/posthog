import { defaultConfig } from './../config/config'

type Bucket = [tokens: number, lastReplenishedTimestamp: number]

export class BucketKeyMissingError extends Error {
    constructor(key: string) {
        super('Bucket with key ' + key + ' is missing. Did you forget to call replenish first?')
        this.name = 'BucketKeyMissingError'
    }
}

export class Storage {
    public buckets: Map<string, Bucket>
    public replenishRate: number
    public bucketCapacity: number

    constructor(bucketCapacity: number, replenishRate: number) {
        this.buckets = new Map()
        this.bucketCapacity = bucketCapacity
        this.replenishRate = replenishRate
    }

    replenish(key: string, now?: number): void {
        const replenish_timestamp: number = now ?? Date.now()
        const bucket = this.buckets.get(key)
        if (bucket === undefined) {
            this.buckets.set(key, [this.bucketCapacity, replenish_timestamp])
            return
        }

        // Replenish the bucket if replenish_timestamp is higher than lastReplenishedTimestamp
        const secondsToReplenish = (replenish_timestamp - bucket[1]) / 1000
        if (secondsToReplenish > 0) {
            bucket[0] += this.replenishRate * secondsToReplenish
            bucket[0] = Math.min(bucket[0], this.bucketCapacity)
            bucket[1] = replenish_timestamp
        }
    }

    consume(key: string, tokens: number): boolean {
        const bucket = this.buckets.get(key)

        if (bucket === undefined) {
            throw new BucketKeyMissingError(key)
        }

        if (bucket[0] < tokens) {
            return false
        }

        bucket[0] -= tokens
        return true
    }
}

export class Limiter {
    public storage: Storage

    constructor(bucketCapacity: number, replenishRate: number) {
        this.storage = new Storage(bucketCapacity, replenishRate)
    }

    consume(key: string, tokens: number, now?: number): boolean {
        this.storage.replenish(key, now)

        return this.storage.consume(key, tokens)
    }
}

export const ConfiguredLimiter: Limiter = new Limiter(
    defaultConfig.EVENT_OVERFLOW_BUCKET_CAPACITY,
    defaultConfig.EVENT_OVERFLOW_BUCKET_REPLENISH_RATE
)

export const IngestionWarningLimiter: Limiter = new Limiter(1, 1.0 / 3600)

export const LoggingLimiter: Limiter = new Limiter(1, 1.0 / 60)
