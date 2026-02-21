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
        this.counters.set(serializedKey, (this.counters.get(serializedKey) ?? 0) + value)

        if (this.counters.size > this.maxKeys) {
            this.evict()
        }
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

    private evict(): void {
        const sorted = Array.from(this.counters.entries()).sort(([, a], [, b]) => b - a)
        const keep = Math.ceil(sorted.length / 2)
        this.counters = new Map(sorted.slice(0, keep))
    }
}
