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
 * addon runs on the libuv threadpool where no OTel context exists, so it reports nanosecond phase
 * boundaries instead and this converts them to spans after the fact — including on failures and
 * contained panics, where `lastOp` names the op that was running when processing stopped.
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
    const taskStartMs = timings.taskStartEpochMs

    const emit = (name: string, startMs: number, endMs: number, decorate?: (span: Span) => void): void => {
        const span = tracer.startSpan(name, { startTime: startMs }, parent)
        decorate?.(span)
        span.end(Math.max(endMs, startMs))
    }

    // SystemTime (Rust) and performance.timeOrigin (JS) are both wall clock; clamp so minor skew
    // can't produce a negative queue span.
    emit('anonymize.queueWait', callStartEpochMs, Math.max(taskStartMs, callStartEpochMs))

    if (timings.decompressStartNs !== null && timings.decompressEndNs !== null) {
        emit(
            'anonymize.decompress',
            taskStartMs + timings.decompressStartNs / NS_PER_MS,
            taskStartMs + timings.decompressEndNs / NS_PER_MS
        )
    }

    if (timings.scrubStartNs !== null) {
        const startMs = taskStartMs + timings.scrubStartNs / NS_PER_MS
        // A missing end boundary means the outer panic guard fired mid-scrub; the await settling
        // "now" is the closest observable end.
        const endMs =
            timings.scrubEndNs !== null
                ? taskStartMs + timings.scrubEndNs / NS_PER_MS
                : performance.timeOrigin + performance.now()
        emit('anonymize.scrub', startMs, endMs, (span) => {
            span.setAttributes({
                'anonymize.route': outcome.route ?? '',
                'anonymize.cv_total_ms': timings.cvTotalNs / NS_PER_MS,
                'anonymize.cv_count': timings.cvCount,
                'anonymize.blur_total_ms': timings.blurTotalNs / NS_PER_MS,
                'anonymize.blur_count': timings.blurCount,
                'anonymize.last_op': timings.lastOp,
            })
            if (outcome.failureReason) {
                span.setStatus({ code: SpanStatusCode.ERROR, message: outcome.failureReason })
                span.setAttribute('anonymize.failure_reason', outcome.failureReason)
            }
        })
    }
}
