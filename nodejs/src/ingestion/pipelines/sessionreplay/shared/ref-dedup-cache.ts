import { LRUCache } from 'lru-cache'
import { Counter, Gauge } from 'prom-client'

/**
 * One ref in this many is remembered after eviction. The ghost list holds keys only and, in sampled
 * space, spans the same number of evictions as the cache holds entries, so a ghost hit means a cache
 * of twice the capacity would still have been holding that ref. Sampling keeps the diagnostic near
 * 6% of the cache's own memory, which is what makes it affordable to leave on across the fleet.
 */
const GHOST_SAMPLE_RATE = 16

const evictionsTotal = new Counter({
    name: 'ml_mirror_ref_cache_evictions_total',
    help: 'Refs dropped from a dedup cache to make room for newer ones',
    labelNames: ['cache'],
})

const capacityProbeTotal = new Counter({
    name: 'ml_mirror_ref_cache_capacity_probe_total',
    help: 'Sampled cache misses split by whether the ref was evicted recently enough that twice the capacity would still hold it. would_hit / (would_hit + would_miss) is the share of misses that doubling the cache would recover, so a value near zero means the cache is big enough and a high value means it is undersized',
    labelNames: ['cache', 'verdict'],
})

const entriesGauge = new Gauge({
    name: 'ml_mirror_ref_cache_entries',
    help: 'Refs currently held in a dedup cache. Below the capacity gauge means the cache has never filled, so it cannot be undersized',
    labelNames: ['cache'],
})

const capacityGauge = new Gauge({
    name: 'ml_mirror_ref_cache_capacity',
    help: 'Configured maximum for a dedup cache, so utilization reads off the metrics instead of the deployed config',
    labelNames: ['cache'],
})

/** Independent of the ref format, so a change to how refs are built cannot skew which ones are sampled. */
function sampleBucket(ref: string): number {
    let hash = 0x811c9dc5
    for (let i = 0; i < ref.length; i++) {
        hash ^= ref.charCodeAt(i)
        hash = Math.imul(hash, 0x01000193)
    }
    return hash >>> 0
}

/**
 * An LRU of refs that reports whether its capacity is the thing limiting its hit rate.
 *
 * Hit rate alone cannot answer that: a low rate looks identical whether the duplicates are genuinely
 * far apart or merely further apart than the cache can reach. The ghost list separates the two, which
 * is the difference between buying hit rate with memory and wasting memory on a working set that was
 * never going to fit.
 */
export class RefDedupCache {
    private readonly cache: LRUCache<string, true> | null
    private readonly ghost: LRUCache<string, true> | null

    constructor(
        private readonly name: string,
        max: number,
        private readonly ghostSampleRate: number = GHOST_SAMPLE_RATE
    ) {
        capacityGauge.labels(name).set(Math.max(0, max))
        entriesGauge.labels(name).set(0)
        if (max <= 0) {
            this.cache = null
            this.ghost = null
            return
        }
        this.ghost = new LRUCache({ max: Math.max(1, Math.floor(max / ghostSampleRate)) })
        this.cache = new LRUCache({
            max,
            dispose: (_value, key, reason) => {
                if (reason !== 'evict') {
                    return
                }
                evictionsTotal.labels(name).inc()
                if (this.isSampled(key)) {
                    this.ghost?.set(key, true)
                }
            },
        })
    }

    public has(ref: string): boolean {
        if (!this.cache) {
            return false
        }
        if (this.cache.get(ref)) {
            return true
        }
        if (this.isSampled(ref)) {
            capacityProbeTotal.labels(this.name, this.ghost?.get(ref) ? 'would_hit' : 'would_miss').inc()
        }
        return false
    }

    public add(ref: string): void {
        if (!this.cache) {
            return
        }
        this.cache.set(ref, true)
        entriesGauge.labels(this.name).set(this.cache.size)
    }

    public delete(ref: string): void {
        if (!this.cache) {
            return
        }
        this.cache.delete(ref)
        entriesGauge.labels(this.name).set(this.cache.size)
    }

    private isSampled(ref: string): boolean {
        return sampleBucket(ref) % this.ghostSampleRate === 0
    }
}
