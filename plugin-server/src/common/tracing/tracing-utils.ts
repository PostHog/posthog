import { Attributes, SpanKind, SpanStatusCode, Tracer, trace } from '@opentelemetry/api'
import { Histogram, Summary, exponentialBuckets } from 'prom-client'

import { defaultConfig } from '~/config/config'
import { timeoutGuard } from '~/utils/db/utils'
import { logger } from '~/utils/logger'
import { captureException } from '~/utils/posthog'

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

const logTime = (startTime: number, statsKey: string, error?: any): void => {
    logger.info('⏱️', `${statsKey} took ${Math.round(performance.now() - startTime)}ms`, {
        error,
        statsKey,
        type: 'instrumented_function_time_log',
    })
}

/**
 * Wraps a function in an OpenTelemetry tracing span.
 */
export function withTracingSpan<T>(
    tracer: Tracer | string,
    name: string,
    attrs: Attributes,
    fn: () => Promise<T>
): Promise<T> {
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
        }
    })
}

/**
 * Wraps a function in an OpenTelemetry tracing span and logs the execution time as a summary metric.
 */
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

    try {
        return withTracingSpan(tracer, name, attrs, fn)
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

    const t = timeoutGuard(timeoutMessage, getLoggingContext, timeout, sendException)
    const startTime = performance.now()
    const end = instrumentedFunctionDuration.startTimer({
        function: key,
    })

    try {
        const result = await withSpan('instrumented_function', key, {}, func)
        end({ success: 'true' })
        if (logExecutionTime) {
            logTime(startTime, key)
        }
        return result
    } catch (error) {
        end({ success: 'false' })
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
