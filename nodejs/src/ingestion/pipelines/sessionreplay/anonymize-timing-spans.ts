import { Span, SpanStatusCode, context, trace } from '@opentelemetry/api'

import type { AnonymizeTimings } from '@posthog/replay-anonymizer'

import { defaultConfig } from '~/common/config/config'

const tracer = trace.getTracer('replay-anonymizer')

const NS_PER_MS = 1e6

export interface AnonymizeOutcome {
    route: string | null
    /** The dlq/drop reason when the addon failed, else null. */
    failureReason: string | null
}

/**
 * Materialize the addon's phase timings as retroactive child spans of the current step span. The
 * addon runs on the libuv threadpool where no OTel context exists, so it reports monotonic offsets
 * instead and this converts them to spans after the fact. All offsets are anchored on the caller's
 * clock at the moment of the addon call, so no cross-clock (JS vs Rust wall time) skew is possible.
 *
 * A phase that started but never ended (contained panic) still gets a span, ended at "now"; on
 * failure the deepest emitted span carries the reason and the `lastOp` that was in flight.
 */
export function recordAnonymizeTimingSpans(
    callStartEpochMs: number,
    timings: AnonymizeTimings | null | undefined,
    outcome: AnonymizeOutcome
): void {
    if (!timings || defaultConfig.DISABLE_OPENTELEMETRY_TRACING) {
        return
    }
    const parent = context.active()
    const at = (offsetNs: number): number => callStartEpochMs + offsetNs / NS_PER_MS
    const nowMs = (): number => performance.timeOrigin + performance.now()

    const decorateFailure = (span: Span): void => {
        span.setAttribute('anonymize.last_op', timings.lastOp)
        if (outcome.failureReason) {
            span.setStatus({ code: SpanStatusCode.ERROR, message: outcome.failureReason })
            span.setAttribute('anonymize.failure_reason', outcome.failureReason)
        }
    }

    interface PhaseSpan {
        name: string
        startMs: number
        endMs: number
        decorate?: (span: Span) => void
    }
    const phases: PhaseSpan[] = []

    if (timings.taskStartNs !== null) {
        phases.push({ name: 'anonymize.queueWait', startMs: callStartEpochMs, endMs: at(timings.taskStartNs) })
    }
    if (timings.decompressStartNs !== null) {
        phases.push({
            name: 'anonymize.decompress',
            startMs: at(timings.decompressStartNs),
            endMs: timings.decompressEndNs !== null ? at(timings.decompressEndNs) : nowMs(),
        })
    }
    if (timings.scrubStartNs !== null) {
        phases.push({
            name: 'anonymize.scrub',
            startMs: at(timings.scrubStartNs),
            endMs: timings.scrubEndNs !== null ? at(timings.scrubEndNs) : nowMs(),
            decorate: (span) => {
                span.setAttributes({
                    'anonymize.route': outcome.route ?? '',
                    'anonymize.cv_total_ms': timings.cvTotalNs / NS_PER_MS,
                    'anonymize.cv_count': timings.cvCount,
                    'anonymize.blur_total_ms': timings.blurTotalNs / NS_PER_MS,
                    'anonymize.blur_count': timings.blurCount,
                })
            },
        })
    }

    phases.forEach((phase, i) => {
        const span = tracer.startSpan(phase.name, { startTime: phase.startMs }, parent)
        phase.decorate?.(span)
        if (i === phases.length - 1) {
            decorateFailure(span)
        }
        span.end(Math.max(phase.endMs, phase.startMs))
    })
}
