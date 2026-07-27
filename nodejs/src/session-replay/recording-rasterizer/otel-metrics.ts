import { Counter, Histogram, metrics as metricsApi } from '@opentelemetry/api'
import { MeterProvider } from '@opentelemetry/sdk-metrics'

import { createCounterWithExemplars, createHistogramWithExemplars, swallowing } from '~/common/metrics/instruments'
import { createOtlpMeterProvider } from '~/common/metrics/otlp-provider'

/**
 * OTLP-pushed twins of the rasterizer's headline prom metrics. The prom side keeps feeding
 * the scrape/VictoriaMetrics dashboards; these land in the PostHog metrics product.
 *
 * The rasterizer has its own initMetrics rather than reusing common/metrics/otel-metrics:
 * that module evaluates defaultConfig at import, which throws without Postgres env vars
 * the rasterizer deployment doesn't have. This one reads the same env names directly and
 * builds the provider through the shared createOtlpMeterProvider.
 *
 * Names and label sets deliberately match the prom metrics so dashboards translate 1:1
 * (the prom activity duration is a Summary; the OTLP twin is a histogram).
 *
 * Instruments are acquired lazily on first record: the OTel metrics API has no proxy
 * provider, so instruments created at module load (before initMetrics runs) would be
 * bound to the noop meter forever.
 */

let provider: MeterProvider | null = null

/** Off unless both OTEL_METRICS_EXPORT_URL and OTEL_METRICS_EXPORT_TOKEN are set. */
export const initMetrics = (): void => {
    if (provider) {
        return
    }
    const url = process.env.OTEL_METRICS_EXPORT_URL
    const token = process.env.OTEL_METRICS_EXPORT_TOKEN
    if (!url || !token) {
        return
    }

    provider = createOtlpMeterProvider({
        url,
        token,
        serviceName: process.env.OTEL_SERVICE_NAME ?? 'recording-rasterizer',
        exportIntervalMillis: parseInt(process.env.OTEL_METRICS_EXPORT_INTERVAL_MS ?? '60000', 10),
    })
    metricsApi.setGlobalMeterProvider(provider)
}

/** Flush and stop the exporter; call once on worker shutdown. */
export const shutdownMetrics = async (): Promise<void> => {
    await provider?.shutdown()
    provider = null
}

interface RasterizerInstruments {
    activitiesTotal: Counter
    activityDuration: Histogram
    errorsTotal: Counter
}

const ACTIVITY_DURATION_BOUNDARIES = [1, 5, 15, 30, 60, 120, 300, 600, 1200]

let instruments: RasterizerInstruments | null = null

function getInstruments(): RasterizerInstruments {
    if (instruments === null) {
        const meter = metricsApi.getMeter('recording-rasterizer')
        instruments = {
            activitiesTotal: createCounterWithExemplars(meter, 'recording_rasterizer_activities_total', {
                description: 'Number of rasterization activities completed',
            }),
            activityDuration: createHistogramWithExemplars(meter, 'recording_rasterizer_activity_duration_seconds', {
                description: 'Total time for the rasterization activity',
                unit: 's',
                advice: { explicitBucketBoundaries: ACTIVITY_DURATION_BOUNDARIES },
            }),
            errorsTotal: createCounterWithExemplars(meter, 'recording_rasterizer_errors_total', {
                description: 'Rasterization errors by code',
            }),
        }
    }
    return instruments
}

export const recordActivity = swallowing((result: 'success' | 'error', seconds: number): void => {
    const { activitiesTotal, activityDuration } = getInstruments()
    activitiesTotal.add(1, { result })
    activityDuration.record(seconds, { result })
})

export const recordError = swallowing((code: string, retryable: boolean): void => {
    getInstruments().errorsTotal.add(1, { code, retryable: retryable.toString() })
})

/** Test seam: forget cached instruments so a test-installed provider is picked up. */
export function resetRasterizerInstrumentsForTests(): void {
    instruments = null
}
