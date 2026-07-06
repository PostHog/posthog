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
 */
export function createTrackedRE2(pattern: string | RegExp, flags?: string, source = 'unknown'): RE2 {
    re2CreationCounter.inc({ source })
    const regex = flags ? new RE2(pattern, flags) : new RE2(pattern)
    return regex as RE2
}
