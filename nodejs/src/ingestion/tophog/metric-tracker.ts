import { parseJSON } from '../../utils/json-parse'

export class MetricTracker {
    private counters: Map<string, number> = new Map()

    constructor(
        readonly metricName: string,
        private readonly topN: number,
        private readonly maxKeys: number
    ) {}

    record(key: Record<string, string>, value: number): void {
        const serializedKey = JSON.stringify(key)
        const existing = this.counters.get(serializedKey)
        if (existing === undefined) {
            if (this.counters.size >= this.maxKeys) {
                const lruKey = this.counters.keys().next().value!
                this.counters.delete(lruKey)
            }
        } else {
            // Move to end of insertion order (mark as most recently used)
            this.counters.delete(serializedKey)
        }

        this.counters.set(serializedKey, (existing ?? 0) + value)
    }

    flush(): Array<{ key: Record<string, string>; value: number }> {
        if (this.counters.size === 0) {
            return []
        }

        const topEntries = Array.from(this.counters.entries())
            .sort(([, a], [, b]) => b - a)
            .slice(0, this.topN)

        this.counters.clear()

        return topEntries.map(([serializedKey, value]) => ({
            key: parseJSON(serializedKey),
            value,
        }))
    }
}
