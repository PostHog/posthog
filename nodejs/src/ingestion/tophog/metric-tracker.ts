import { parseJSON } from '../../utils/json-parse'

export interface Tracker {
    readonly metricName: string
    record(key: Record<string, string>, value: number): void
    flush(): Array<{ key: Record<string, string>; value: number }>
}

export class MetricTracker<TStored> {
    private entries: Map<string, TStored> = new Map()

    constructor(
        readonly metricName: string,
        private readonly topN: number,
        private readonly maxKeys: number,
        private readonly store: (stored: TStored | undefined, value: number) => TStored,
        private readonly compute: (stored: TStored) => number
    ) {}

    record(key: Record<string, string>, value: number): void {
        const serializedKey = JSON.stringify(key)
        this.entries.set(serializedKey, this.store(this.entries.get(serializedKey), value))

        if (this.entries.size > this.maxKeys) {
            this.evict()
        }
    }

    flush(): Array<{ key: Record<string, string>; value: number }> {
        if (this.entries.size === 0) {
            return []
        }

        const computed = Array.from(this.entries.entries()).map(
            ([serializedKey, stored]) => [serializedKey, this.compute(stored)] as const
        )

        this.entries.clear()

        return computed
            .sort(([, a], [, b]) => b - a)
            .slice(0, this.topN)
            .map(([serializedKey, value]) => ({ key: parseJSON(serializedKey), value }))
    }

    private evict(): void {
        const sorted = Array.from(this.entries.entries()).sort(([, a], [, b]) => this.compute(b) - this.compute(a))
        const keep = Math.ceil(sorted.length / 2)
        this.entries = new Map(sorted.slice(0, keep))
    }
}

export class AddingMetricTracker {
    private readonly tracker: MetricTracker<number>

    constructor(name: string, topN: number, maxKeys: number) {
        this.tracker = new MetricTracker(
            name,
            topN,
            maxKeys,
            (s, v) => (s ?? 0) + v,
            (s) => s
        )
    }

    get metricName(): string {
        return this.tracker.metricName
    }

    record(key: Record<string, string>, value: number): void {
        this.tracker.record(key, value)
    }

    flush(): Array<{ key: Record<string, string>; value: number }> {
        return this.tracker.flush()
    }
}

export class AverageMetricTracker {
    private readonly tracker: MetricTracker<{ count: number; sum: number }>

    constructor(name: string, topN: number, maxKeys: number) {
        this.tracker = new MetricTracker(
            name,
            topN,
            maxKeys,
            (s, v) => ({ count: (s?.count ?? 0) + 1, sum: (s?.sum ?? 0) + v }),
            (s) => s.sum / s.count
        )
    }

    get metricName(): string {
        return this.tracker.metricName
    }

    record(key: Record<string, string>, value: number): void {
        this.tracker.record(key, value)
    }

    flush(): Array<{ key: Record<string, string>; value: number }> {
        return this.tracker.flush()
    }
}
