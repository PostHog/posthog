import { Counter, metrics as metricsApi } from '@opentelemetry/api'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics'
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from '@opentelemetry/semantic-conventions'
import { hostname } from 'os'

import { defaultConfig } from '~/common/config/config'
import { logger } from '~/common/utils/logger'
import { registerShutdownHandler } from '~/lifecycle'

import { counterWithExemplars } from './exemplars'
import { OtlpJsonMetricExporter } from './otlp-json-exporter'

/**
 * OTLP metrics push — the same OTel-SDK path customers use, pointed at our own
 * ingest (capture-logs /v1/metrics). Complements tracing/otel.ts (spans) and the
 * collector-shipped container logs: with this, a service pushes all three
 * signals instead of having its metrics scraped.
 *
 * Off unless both OTEL_METRICS_EXPORT_URL and OTEL_METRICS_EXPORT_TOKEN are set,
 * so nothing changes for deployments that don't opt in.
 */

let provider: MeterProvider | null = null

export const initMetrics = (): void => {
    if (provider) {
        return
    }
    if (!defaultConfig.OTEL_METRICS_EXPORT_URL || !defaultConfig.OTEL_METRICS_EXPORT_TOKEN) {
        return
    }

    logger.info('Starting OTLP metrics push', { endpoint: defaultConfig.OTEL_METRICS_EXPORT_URL })

    provider = new MeterProvider({
        resource: resourceFromAttributes({
            [ATTR_SERVICE_NAME]:
                defaultConfig.OTEL_SERVICE_NAME ?? `node-${defaultConfig.PLUGIN_SERVER_MODE ?? 'nodejs'}`,
            [ATTR_SERVICE_VERSION]: process.env.COMMIT_SHA ?? 'dev',
            // Per-replica identity. Without it every pod shares one series, and
            // their interleaved cumulative counters read as constant resets —
            // rate()/increase() overcount by roughly the replica count.
            'service.instance.id': hostname(),
        }),
        readers: [
            new PeriodicExportingMetricReader({
                // Not the stock OTLPMetricExporter: the upstream JS pipeline drops
                // exemplars, and the metric-to-trace pivot needs them (see the
                // exporter's docstring).
                exporter: new OtlpJsonMetricExporter({
                    url: defaultConfig.OTEL_METRICS_EXPORT_URL,
                    headers: { Authorization: `Bearer ${defaultConfig.OTEL_METRICS_EXPORT_TOKEN}` },
                }),
                exportIntervalMillis: defaultConfig.OTEL_METRICS_EXPORT_INTERVAL_MS,
            }),
        ],
    })
    metricsApi.setGlobalMeterProvider(provider)

    registerShutdownHandler(async () => {
        await provider?.shutdown()
    })
}

let piiReplacementsCounter: Counter | null = null

/**
 * PII replacements performed by the ingest scrubber. Previously only visible in
 * per-team billing usage rows — no operational metric existed for it at all.
 *
 * The counter is acquired lazily on first record: the OTel metrics API has no
 * proxy provider, so a counter created at module load (before initMetrics runs)
 * would be bound to the noop meter forever.
 */
export function recordPiiReplacements(source: string, count: number): void {
    if (count <= 0) {
        return
    }
    if (piiReplacementsCounter === null) {
        piiReplacementsCounter = counterWithExemplars(
            'logs_pii_replacements_total',
            metricsApi.getMeter('logs-ingestion').createCounter('logs_pii_replacements_total', {
                description: 'PII values replaced by the ingest scrubber, by pipeline source (logs | traces).',
            })
        )
    }
    piiReplacementsCounter.add(count, { source })
}

/** Test seam: forget the cached counter so a test-installed provider is picked up. */
export function resetPiiReplacementsCounterForTests(): void {
    piiReplacementsCounter = null
}
