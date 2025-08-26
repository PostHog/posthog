import { Attributes, SpanKind, SpanStatusCode, Tracer, trace } from '@opentelemetry/api'
import { Summary } from 'prom-client'

const instrumentedFnSummary = new Summary({
    name: 'instrumented_fn_duration_ms',
    help: 'Duration of instrumented functions',
    labelNames: ['metricName', 'tag'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

// Helper method to instrument a function - instruments it in opentelem primarily with a prom metric too
export function withSpan<T>(
    tracer: Tracer | string,
    name: string,
    attrs: Attributes,
    fn: () => Promise<T>
): Promise<T> {
    const stopTimer = instrumentedFnSummary
        .labels({
            metricName: name,
            tag: attrs.tag ? String(attrs.tag) : undefined,
        })
        .startTimer()

    const _tracer = typeof tracer === 'string' ? trace.getTracer(tracer) : tracer
    return _tracer.startActiveSpan(name, { kind: SpanKind.CLIENT, attributes: attrs }, async (span) => {
        try {
            const out = await fn()
            span.setStatus({ code: SpanStatusCode.OK })
            return out
        } catch (e: any) {
            span.recordException(e)
            span.setStatus({ code: SpanStatusCode.ERROR, message: e?.message })
            throw e
        } finally {
            span.end()
            stopTimer()
        }
    })
}
