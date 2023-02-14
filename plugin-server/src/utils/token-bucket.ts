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
        if (typeof now === 'undefined') {
            now = Date.now()
        }

        if (this.buckets.has(key) === false) {
            this.buckets.set(key, [this.bucketCapacity, now])
            return
        }

        // We have checked the key exists already, so this cannot be undefined
        const bucket: Bucket = this.buckets.get(key)!

        // replenishRate is per second, but timestamps are in milliseconds
        const replenishedTokens = this.replenishRate * ((now - bucket[1]) / 1000)
        bucket[0] += replenishedTokens
        bucket[1] = now
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
