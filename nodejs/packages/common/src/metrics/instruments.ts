import { Counter, Histogram, Meter, MetricOptions } from '@opentelemetry/api'

import { counterWithExemplars, histogramWithExemplars } from './exemplars'

/**
 * Shared helpers for the OTLP twin modules (logs, session replay ingestion, rasterizer),
 * so every instrument gets the exemplar wrap and every record path swallows telemetry
 * errors the same way.
 */

// The wrappers buffer an exemplar (active span context) per record, which the
// OTLP JSON exporter attaches at export — the upstream SDK path can't do this.
export const createCounterWithExemplars = (meter: Meter, name: string, options?: MetricOptions): Counter =>
    counterWithExemplars(name, meter.createCounter(name, options))

export const createHistogramWithExemplars = (meter: Meter, name: string, options?: MetricOptions): Histogram =>
    histogramWithExemplars(name, meter.createHistogram(name, options))

/**
 * Twin recording runs in hot paths, finally blocks, and error handlers. A throw here
 * would mask the real processing error, so recording failures are swallowed.
 */
export function swallowing<Args extends unknown[]>(record: (...args: Args) => void): (...args: Args) => void {
    return (...args: Args): void => {
        try {
            record(...args)
        } catch {
            // never let telemetry break the caller
        }
    }
}
