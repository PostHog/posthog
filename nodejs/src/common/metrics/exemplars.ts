import { Attributes, Counter, Histogram, TraceFlags, isSpanContextValid, trace } from '@opentelemetry/api'

/**
 * Exemplar side-buffer for the OTLP metrics push.
 *
 * The upstream OTel JS SDK ships exemplar classes but never wires them into
 * recording or export (as of sdk-metrics 2.7.1 nothing samples exemplars and
 * otlp-transformer never serializes them), so metrics pushed through the SDK
 * can never link to traces. Instead, the instrument wrappers below capture the
 * active sampled span context at record time, keyed by series (instrument name
 * + attributes), and OtlpJsonMetricExporter attaches the buffered exemplars to
 * the matching data points at export time.
 *
 * One exemplar per series per export interval (last measurement wins) — the
 * metric-to-trace pivot needs one representative trace, not every one.
 */

export interface BufferedExemplar {
    value: number
    timeUnixNano: string
    traceId: string
    spanId: string
}

// Bounds memory if a caller records against unexpectedly high-cardinality
// attributes; new series beyond the cap just go exemplar-less until a drain.
const MAX_BUFFERED_EXEMPLARS = 512

let buffer = new Map<string, BufferedExemplar>()

export function exemplarKey(instrumentName: string, attributes?: Attributes): string {
    const sorted = Object.entries(attributes ?? {}).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    return `${instrumentName}|${JSON.stringify(sorted)}`
}

export function offerExemplar(instrumentName: string, value: number, attributes?: Attributes): void {
    const spanContext = trace.getActiveSpan()?.spanContext()
    if (!spanContext || !isSpanContextValid(spanContext) || !(spanContext.traceFlags & TraceFlags.SAMPLED)) {
        return
    }
    const key = exemplarKey(instrumentName, attributes)
    if (!buffer.has(key) && buffer.size >= MAX_BUFFERED_EXEMPLARS) {
        return
    }
    buffer.set(key, {
        value,
        timeUnixNano: (BigInt(Date.now()) * 1_000_000n).toString(),
        traceId: spanContext.traceId,
        spanId: spanContext.spanId,
    })
}

/** Hands the current buffer to the exporter and starts a fresh interval. */
export function drainExemplars(): Map<string, BufferedExemplar> {
    const drained = buffer
    buffer = new Map()
    return drained
}

/** Same interface as the wrapped counter, so call sites don't change. */
export function counterWithExemplars(instrumentName: string, counter: Counter): Counter {
    return {
        add: (value: number, attributes?: Attributes, ctx?: unknown): void => {
            offerExemplar(instrumentName, value, attributes)
            counter.add(value, attributes, ctx as never)
        },
    }
}

export function histogramWithExemplars(instrumentName: string, histogram: Histogram): Histogram {
    return {
        record: (value: number, attributes?: Attributes, ctx?: unknown): void => {
            offerExemplar(instrumentName, value, attributes)
            histogram.record(value, attributes, ctx as never)
        },
    }
}

export function resetExemplarsForTests(): void {
    buffer = new Map()
}
