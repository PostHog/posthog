import { logger } from '../../../utils/logger'

export class TopTracker {
    private counters: Map<string, Map<string, number>> = new Map()

    /**
     * Increment the counter for a specific metric and key
     * @param metric - The metric name (e.g., 'session_size', 'message_count')
     * @param key - The key to track (e.g., session_id, team_id)
     * @param count - The amount to increment by (defaults to 1)
     */
    public increment(metric: string, key: string, count: number = 1): void {
        let metricCounters = this.counters.get(metric)
        if (!metricCounters) {
            metricCounters = new Map()
            this.counters.set(metric, metricCounters)
        }

        const currentCount = metricCounters.get(key) ?? 0
        metricCounters.set(key, currentCount + count)
    }

    /**
     * Log the top N entries for each metric and reset all counters
     * @param topN - Number of top entries to log for each metric
     */
    public logAndReset(topN: number): void {
        for (const [metric, metricCounters] of this.counters.entries()) {
            if (metricCounters.size === 0) {
                continue
            }

            // Sort entries by count descending and take top N
            const sortedEntries = Array.from(metricCounters.entries())
                .sort(([, a], [, b]) => b - a)
                .slice(0, topN)

            // Format for logging
            const topEntries = sortedEntries.map(([key, count]) => ({ key, count }))

            logger.info('📊 Top entries for metric', {
                metric,
                topN,
                entries: topEntries,
                totalKeys: metricCounters.size,
            })
        }

        // Reset all counters
        this.counters.clear()
    }

    /**
     * Get the current count for a specific metric and key (useful for testing)
     */
    public getCount(metric: string, key: string): number {
        return this.counters.get(metric)?.get(key) ?? 0
    }

    /**
     * Get all metrics being tracked
     */
    public getMetrics(): string[] {
        return Array.from(this.counters.keys())
    }
}
