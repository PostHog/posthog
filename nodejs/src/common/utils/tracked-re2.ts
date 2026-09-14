import { Counter } from 'prom-client'
import RE2 from 're2'

/**
 * Minimal tracking wrapper for RE2 allocations to diagnose memory leak sources.
 *
 * This adds a Prometheus counter to track how many RE2 objects are created.
 * Use this to correlate RE2 creation rate with memory growth rate in Grafana.
 *
 * Usage in Grafana:
 *   rate(re2_objects_created_total[1m])  # RE2 objects/sec
 *   rate(process_rss_bytes[1m])          # Memory growth/sec
 */

const re2CreationCounter = new Counter({
    name: 're2_objects_created_total',
    help: 'Total number of RE2 regex objects created',
    labelNames: ['source'],
})

/**
 * Create a tracked RE2 instance.
 *
 * @param pattern The regex pattern (string or RegExp)
 * @param flags Optional regex flags (e.g., 'g', 'i', 'm')
 * @param source Label to identify where this allocation came from (for debugging)
 * @returns RE2 instance
 *
 * Instances are cached by (pattern, flags) in a small LRU: RE2 compilation is the
 * dominant cost of a regex evaluation, and hot paths (log transformations, sampling,
 * PII scrub) recompile the same handful of patterns for every record at 100k+/s.
 * Only string patterns without the `g` flag are cached: a `g`/`y` regex carries
 * mutable `lastIndex` state across exec() calls, so sharing it would corrupt matches.
 * The cache is bounded so adversarial or high-cardinality patterns cannot grow it
 * without limit (each RE2 holds native memory).
 */
const RE2_CACHE_MAX_ENTRIES = 256
const re2Cache = new Map<string, RE2>()

export function createTrackedRE2(pattern: string | RegExp, flags?: string, source = 'unknown'): RE2 {
    const cacheable = typeof pattern === 'string' && !flags?.includes('g') && !flags?.includes('y')
    if (!cacheable) {
        re2CreationCounter.inc({ source })
        return (flags ? new RE2(pattern, flags) : new RE2(pattern)) as RE2
    }

    const key = `${flags ?? ''}${pattern}`
    const cached = re2Cache.get(key)
    if (cached) {
        // Refresh recency: delete+set moves the entry to the LRU tail.
        re2Cache.delete(key)
        re2Cache.set(key, cached)
        return cached
    }

    re2CreationCounter.inc({ source })
    const regex = (flags ? new RE2(pattern, flags) : new RE2(pattern)) as RE2
    re2Cache.set(key, regex)
    if (re2Cache.size > RE2_CACHE_MAX_ENTRIES) {
        // Evict the least-recently-used entry (Map preserves insertion order).
        const oldest = re2Cache.keys().next().value
        if (oldest !== undefined) {
            re2Cache.delete(oldest)
        }
    }
    return regex
}
