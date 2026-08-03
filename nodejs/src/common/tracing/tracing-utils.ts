import {
    Attributes,
    HrTime,
    Link,
    SpanContext,
    SpanKind,
    SpanStatusCode,
    TraceFlags,
    Tracer,
    trace,
} from '@opentelemetry/api'
import { Counter, Histogram, Summary, exponentialBuckets } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { timeoutGuard } from '~/common/utils/db/utils'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

const instrumentedFnSummary = new Summary({
    name: 'instrumented_fn_duration_ms',
    help: 'Duration of instrumented functions',
    labelNames: ['metricName', 'tag'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

const instrumentedFunctionDuration = new Histogram({
    name: 'instrumented_function_duration_seconds',
    help: 'Processing time and success status of internal functions',
    labelNames: ['function', 'success'],
    // We need to cover a pretty wide range, so buckets are set pretty coarse for now
    // and cover 25ms -> 102seconds. We can revisit them later on.
    buckets: exponentialBuckets(0.025, 4, 7),
})

const instrumentedFunctionTimeout = new Counter({
    name: 'instrumented_function_timeout_total',
    help: 'Number of times an instrumented function exceeded its timeout threshold',
    labelNames: ['function'],
})

const logTime = (startTime: number, statsKey: string, error?: any): void => {
    logger.info('⏱️', `${statsKey} took ${Math.round(performance.now() - startTime)}ms`, {
        error,
        statsKey,
        type: 'instrumented_function_time_log',
    })
}

function getHighResTimestamp(): HrTime {
    // performance.timeOrigin: absolute start time of the process
    // performance.now(): high-res relative time since process start
    const epochMillis = performance.timeOrigin + performance.now()
    const seconds = Math.floor(epochMillis / 1000)
    const nanos = Math.round((epochMillis % 1000) * 1_000_000)
    return [seconds, nanos]
}
// Cap on how many capture-trace links we attach to a single ingestion batch
// span. OpenTelemetry's default max links per span is 128; a wide batch can span
// more distinct capture requests than that.
const MAX_BATCH_TRACE_LINKS = 128

const batchTraceLinksTruncatedCounter = new Counter({
    name: 'ingestion_batch_trace_links_truncated_total',
    help: 'Batches whose distinct capture-trace links exceeded the per-span cap and were truncated',
})

const INVALID_TRACE_ID = '0'.repeat(32)
const INVALID_SPAN_ID = '0'.repeat(16)
// W3C `traceparent`: version "00", 32-hex trace id, 16-hex span id, 2-hex flags.
const TRACEPARENT_REGEX = /^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$/

/**
 * Parses a W3C `traceparent` string into a remote {@link SpanContext}, or null
 * when it is malformed or carries an all-zero (invalid) trace/span id.
 */
export function spanContextFromTraceparent(traceparent: string): SpanContext | null {
    const match = TRACEPARENT_REGEX.exec(traceparent)
    if (!match) {
        return null
    }
    const [, traceId, spanId, flags] = match
    if (traceId === INVALID_TRACE_ID || spanId === INVALID_SPAN_ID) {
        return null
    }
    return { traceId, spanId, traceFlags: parseInt(flags, 16), isRemote: true }
}

/**
 * Builds OpenTelemetry span links from a batch of W3C `traceparent` strings so a
 * batch-processing span can reference every capture trace that fed it — the
 * standard fan-in pattern for a consumer that mixes messages from many upstream
 * traces. Links are deduped by trace id, restricted to sampled traces (linking
 * to an unsampled trace dangles), and capped at {@link MAX_BATCH_TRACE_LINKS}.
 */
export function linksFromTraceparents(traceparents: Iterable<string>): Link[] {
    const seen = new Set<string>()
    const links: Link[] = []
    let truncated = false
    for (const traceparent of traceparents) {
        const spanContext = spanContextFromTraceparent(traceparent)
        if (!spanContext) {
            continue
        }
        if ((spanContext.traceFlags & TraceFlags.SAMPLED) === 0) {
            continue
        }
        if (seen.has(spanContext.traceId)) {
            continue
        }
        seen.add(spanContext.traceId)
        if (links.length >= MAX_BATCH_TRACE_LINKS) {
            truncated = true
            continue
        }
        links.push({ context: spanContext })
    }
    if (truncated) {
        batchTraceLinksTruncatedCounter.inc()
    }
    return links
}

/**
 * Wraps a function in an OpenTelemetry tracing span.
 */
export function withTracingSpan<T>(
    tracer: Tracer | string,
    name: string,
    attrs: Attributes,
    fn: () => Promise<T>,
    links?: Link[]
): Promise<T> {
    const _tracer = typeof tracer === 'string' ? trace.getTracer(tracer) : tracer
    const startHrTime = getHighResTimestamp()
    return _tracer.startActiveSpan(
        name,
        { kind: SpanKind.CLIENT, attributes: attrs, startTime: startHrTime, links },
        async (span) => {
            try {
                const out = await fn()
                span.setStatus({ code: SpanStatusCode.OK })
                return out
            } catch (e: any) {
                span.recordException(e)
                span.setStatus({ code: SpanStatusCode.ERROR, message: e?.message })
                throw e
            } finally {
                span.end(getHighResTimestamp())
            }
        }
    )
}

/**
 * Wraps a function in an OpenTelemetry tracing span and logs the execution time as a summary metric.
 */
export async function withSpan<T>(
    tracer: Tracer | string,
    name: string,
    attrs: Attributes,
    fn: () => Promise<T>,
    links?: Link[]
): Promise<T> {
    const stopTimer = instrumentedFnSummary
        .labels({
            metricName: name,
            tag: attrs.tag ? String(attrs.tag) : undefined,
        })
        .startTimer()

    try {
        return await withTracingSpan(tracer, name, attrs, fn, links)
    } finally {
        stopTimer()
    }
}

interface FunctionInstrumentationOptions {
    key: string
    timeoutMs?: number
    timeoutMessage?: string
    getLoggingContext?: () => Record<string, any>
    logExecutionTime?: boolean
    sendException?: boolean
    measureTime?: boolean
    // OpenTelemetry span links, e.g. the capture traces that fed a Kafka batch.
    links?: Link[]
}

/**
 * Wraps a function in a timeout guard and a prometheus metric.
 */

export async function instrumentFn<T>(
    options: string | FunctionInstrumentationOptions,
    func: () => Promise<T>
): Promise<T> {
    const key = typeof options === 'string' ? options : options.key
    const timeoutMessage =
        (typeof options === 'string' ? undefined : options.timeoutMessage) ?? `Timeout warning for '${key}'!`
    const getLoggingContext = (typeof options === 'string' ? undefined : options.getLoggingContext) ?? undefined
    const timeout = (typeof options === 'string' ? undefined : options.timeoutMs) ?? defaultConfig.TASK_TIMEOUT * 1000
    const sendException = (typeof options === 'string' ? undefined : options.sendException) ?? true
    const logExecutionTime = (typeof options === 'string' ? undefined : options.logExecutionTime) ?? false
    const measureTime = (typeof options === 'string' ? undefined : options.measureTime) ?? true
    const links = typeof options === 'string' ? undefined : options.links

    const t = timeoutGuard(timeoutMessage, getLoggingContext, timeout, sendException, () => {
        instrumentedFunctionTimeout.labels({ function: key }).inc()
    })
    const startTime = performance.now()
    const end = measureTime ? instrumentedFunctionDuration.startTimer({ function: key }) : undefined

    try {
        // Skip expensive span creation when tracing is disabled
        const result = defaultConfig.DISABLE_OPENTELEMETRY_TRACING
            ? await func()
            : await withSpan('instrumented_function', key, {}, func, links)
        end?.({ success: 'true' })
        if (logExecutionTime) {
            logTime(startTime, key)
        }
        return result
    } catch (error) {
        end?.({ success: 'false' })
        logger.info('🔔', error)
        if (logExecutionTime) {
            logTime(startTime, key, error)
        }
        if (sendException) {
            captureException(error)
        }
        throw error
    } finally {
        clearTimeout(t)
    }
}

/**
 * Decorator that can be applied to class methods or standalone functions to add tracing and instrumentation.
 *
 * @param options - Either a string key or FunctionInstrumentationOptions object
 * @returns A decorator function that wraps the original method/function
 *
 * @example
 * // For class methods:
 * class MyService {
 *   @instrumented('my-service-method')
 *   async myMethod() {
 *     // method implementation
 *   }
 * }
 *
 * // For standalone functions:
 * const myFunction = instrumented('my-function')(async () => {
 *   // function implementation
 * })
 */
export function instrumented(options: string | FunctionInstrumentationOptions) {
    return function <T extends (...args: any[]) => Promise<any>>(
        target: any,
        propertyKey?: string | symbol,
        descriptor?: TypedPropertyDescriptor<T>
    ): any {
        // If used as a method decorator (class method)
        if (descriptor && propertyKey) {
            const originalMethod = descriptor.value
            if (!originalMethod) {
                throw new Error('Cannot apply instrumented decorator to non-function property')
            }

            descriptor.value = async function (this: any, ...args: any[]): Promise<any> {
                return instrumentFn(options, () => originalMethod.apply(this, args))
            } as T

            return descriptor
        }

        // If used as a function decorator (standalone function)
        if (typeof target === 'function') {
            return async function (this: any, ...args: any[]): Promise<any> {
                return instrumentFn(options, () => target.apply(this, args))
            }
        }

        throw new Error('instrumented decorator can only be applied to functions or methods')
    }
}
