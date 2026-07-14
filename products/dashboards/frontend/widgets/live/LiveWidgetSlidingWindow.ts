import type { LiveEvent } from '~/types'

/** Maps a streamed event to a breakdown value; return null to skip the event for that domain. */
export type LiveWidgetEventExtractor = (event: LiveEvent) => string | null

export interface LiveWidgetSeedBucket {
    minute: string
    value: string
    views: number
}

const toEpochSeconds = (iso: string): number | null => {
    const ms = new Date(iso).getTime()
    return Number.isFinite(ms) ? ms / 1000 : null
}

const toMinuteBucket = (seconds: number): number => Math.floor(seconds / 60) * 60

/**
 * Minute-bucketed sliding window behind live dashboard widgets: an overall event count plus
 * named breakdown domains (each fed by a `LiveWidgetEventExtractor` over the streamed events).
 *
 * Each domain can be re-seeded independently because each widget's run_widgets result arrives
 * separately. A domain's seed carries a `generatedAt` server timestamp; streamed events at or
 * before it are dropped for that domain so a re-seed never double counts.
 *
 * Seeds arrive once per domain from the dashboard's initial run_widgets fetch (and again on manual
 * tile refresh), then the stream keeps the window moving. Seeds MERGE via per-bucket max rather
 * than replacing: the SSE stream reads Kafka directly while seeds read ClickHouse, which can lag
 * ingestion — a replace would wipe stream-accumulated counts with stale (or empty) server data.
 * Both sources count the same events, so max never double counts and converges to server truth.
 */
export class LiveWidgetSlidingWindow<D extends string = string> {
    private readonly windowMinutes: number
    private readonly extractors: Record<D, LiveWidgetEventExtractor>
    private countsByMinute = new Map<number, number>()
    private breakdowns: Record<D, Map<number, Map<string, number>>>
    private newerThan: Record<string, number>

    constructor(options: { windowMinutes: number; breakdowns: Record<D, LiveWidgetEventExtractor> }) {
        this.windowMinutes = options.windowMinutes
        this.extractors = options.breakdowns
        this.breakdowns = Object.fromEntries(
            Object.keys(options.breakdowns).map((domain) => [domain, new Map<number, Map<string, number>>()])
        ) as Record<D, Map<number, Map<string, number>>>
        this.newerThan = Object.fromEntries(['counts', ...Object.keys(options.breakdowns)].map((key) => [key, 0]))
    }

    addEvent(event: LiveEvent): void {
        const seconds = toEpochSeconds(event.timestamp)
        if (seconds === null) {
            return
        }
        const minute = toMinuteBucket(seconds)

        if (seconds > this.newerThan.counts) {
            this.countsByMinute.set(minute, (this.countsByMinute.get(minute) ?? 0) + 1)
        }

        for (const domain of Object.keys(this.extractors) as D[]) {
            if (seconds > this.newerThan[domain]) {
                const value = this.extractors[domain](event)
                if (value !== null) {
                    this.incrementBreakdown(domain, minute, value)
                }
            }
        }
    }

    mergeCountSeed(buckets: { minute: string; count: number }[], generatedAt: string): void {
        const merged = new Map<number, number>()
        for (const bucket of buckets) {
            const seconds = toEpochSeconds(bucket.minute)
            if (seconds !== null) {
                const minute = toMinuteBucket(seconds)
                merged.set(minute, (merged.get(minute) ?? 0) + bucket.count)
            }
        }
        for (const [minute, count] of this.countsByMinute) {
            merged.set(minute, Math.max(merged.get(minute) ?? 0, count))
        }
        this.countsByMinute = merged
        this.newerThan.counts = toEpochSeconds(generatedAt) ?? this.newerThan.counts
    }

    mergeBreakdownSeed(domain: D, buckets: LiveWidgetSeedBucket[], generatedAt: string): void {
        const merged = new Map<number, Map<string, number>>()
        for (const bucket of buckets) {
            const seconds = toEpochSeconds(bucket.minute)
            if (seconds === null) {
                continue
            }
            const minute = toMinuteBucket(seconds)
            const byValue = merged.get(minute) ?? new Map<string, number>()
            byValue.set(bucket.value, (byValue.get(bucket.value) ?? 0) + bucket.views)
            merged.set(minute, byValue)
        }
        for (const [minute, byValue] of this.breakdowns[domain]) {
            const mergedByValue = merged.get(minute) ?? new Map<string, number>()
            for (const [value, views] of byValue) {
                mergedByValue.set(value, Math.max(mergedByValue.get(value) ?? 0, views))
            }
            merged.set(minute, mergedByValue)
        }
        this.breakdowns[domain] = merged
        this.newerThan[domain] = toEpochSeconds(generatedAt) ?? this.newerThan[domain]
    }

    prune(nowSeconds: number = Date.now() / 1000): void {
        const cutoff = toMinuteBucket(nowSeconds) - this.windowMinutes * 60
        for (const minute of this.countsByMinute.keys()) {
            if (minute < cutoff) {
                this.countsByMinute.delete(minute)
            }
        }
        for (const byMinute of Object.values<Map<number, Map<string, number>>>(this.breakdowns)) {
            for (const minute of byMinute.keys()) {
                if (minute < cutoff) {
                    byMinute.delete(minute)
                }
            }
        }
    }

    totalCount(): number {
        let total = 0
        for (const count of this.countsByMinute.values()) {
            total += count
        }
        return total
    }

    breakdownTotals(domain: D): { value: string; views: number }[] {
        const totals = new Map<string, number>()
        for (const byValue of this.breakdowns[domain].values()) {
            for (const [value, views] of byValue) {
                totals.set(value, (totals.get(value) ?? 0) + views)
            }
        }
        return [...totals.entries()]
            .map(([value, views]) => ({ value, views }))
            .sort((a, b) => b.views - a.views || a.value.localeCompare(b.value))
    }

    private incrementBreakdown(domain: D, minute: number, value: string): void {
        const byValue = this.breakdowns[domain].get(minute) ?? new Map<string, number>()
        byValue.set(value, (byValue.get(value) ?? 0) + 1)
        this.breakdowns[domain].set(minute, byValue)
    }
}
