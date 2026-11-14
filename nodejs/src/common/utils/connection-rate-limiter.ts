import { LRUCache } from 'lru-cache'

type Bucket = { tokens: number; updatedAt: number }

export type ConnectionRateLimiterOptions = {
    perSecond: number
    burst: number
}

/**
 * Limits how fast new connections open to each destination IP address. Behind a NAT gateway every new connection takes
 * a source port for its destination IP and port, and a gateway IP has about 55,000 of them. A request on a kept-alive
 * socket opens no connection, so a healthy origin rarely takes a token. An origin that times out or closes its
 * connections makes every request open a new one, and that origin alone runs out of tokens.
 */
export class ConnectionRateLimiter {
    // Evicting a bucket only resets that address to a full burst, so the cap on entries costs little accuracy.
    private readonly buckets = new LRUCache<string, Bucket>({ max: 10_000 })

    constructor(private readonly options: ConnectionRateLimiterOptions) {}

    /** Takes a token for the address. Returns false when the address has none left. */
    tryTake(address: string): boolean {
        const bucket = this.refilled(address)
        this.buckets.set(address, bucket)
        if (bucket.tokens < 1) {
            return false
        }
        bucket.tokens--
        return true
    }

    private refilled(address: string): Bucket {
        const now = Date.now()
        const bucket = this.buckets.get(address) ?? { tokens: this.options.burst, updatedAt: now }
        bucket.tokens = Math.min(
            this.options.burst,
            bucket.tokens + ((now - bucket.updatedAt) / 1000) * this.options.perSecond
        )
        bucket.updatedAt = now
        return bucket
    }
}
