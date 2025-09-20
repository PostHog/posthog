import { SpanStatusCode } from '@opentelemetry/api'
import { ReadableSpan, SpanExporter } from '@opentelemetry/sdk-trace-node'

function durationMs(s: ReadableSpan): number {
    const [s0, n0] = s.startTime
    const [s1, n1] = s.endTime!
    return (s1 - s0) * 1_000 + (n1 - n0) / 1_000_000
}

function hasError(s: ReadableSpan): boolean {
    return s.status?.code === SpanStatusCode.ERROR
}

type Key = string // `${traceId}:${parentSpanId}:${name}`

/**
 * This exporter is used to cap the number of spans exported to the backend.
 * It keeps the last N siblings per (traceId,parentSpanId,name) and discards the rest.
 * It also keeps spans with an error or a duration >= minDurationMs.
 */
export class CappedSiblingsExporter implements SpanExporter {
    constructor(
        private delegate: SpanExporter,
        private opts: { maxPerGroup: number; minDurationMs?: number } = { maxPerGroup: 2 }
    ) {}

    export(spans: ReadableSpan[], done: (r: { code: any }) => void): void {
        const counts = new Map<Key, number>()

        const keep: ReadableSpan[] = []

        for (const s of spans) {
            // always keep roots
            if (!s.parentSpanContext?.spanId) {
                keep.push(s)
                continue
            }

            // keep by exception or latency
            if (hasError(s) || (this.opts.minDurationMs && durationMs(s) >= this.opts.minDurationMs)) {
                keep.push(s)
                continue
            }

            const key: Key = `${s.spanContext().traceId}:${s.parentSpanContext?.spanId}:${s.name}`
            const n = (counts.get(key) ?? 0) + 1
            if (n <= this.opts.maxPerGroup) {
                keep.push(s)
            }
            counts.set(key, n)
        }

        if (keep.length === 0) {
            return done({ code: 0 })
        }
        this.delegate.export(keep, done)
    }

    shutdown(): Promise<void> {
        return this.delegate.shutdown()
    }
}
