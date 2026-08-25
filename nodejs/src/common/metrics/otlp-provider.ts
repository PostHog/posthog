import { resourceFromAttributes } from '@opentelemetry/resources'
import { MeterProvider, PeriodicExportingMetricReader } from '@opentelemetry/sdk-metrics'
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from '@opentelemetry/semantic-conventions'
import { hostname } from 'os'

import { OtlpJsonMetricExporter } from './otlp-json-exporter'

export interface OtlpMeterProviderOptions {
    url: string
    token: string
    serviceName: string
    exportIntervalMillis: number
}

/**
 * One MeterProvider wired for the PostHog Metrics product ingest. Shared so every service
 * gets the same exporter (the exemplar-preserving OTLP/JSON one) and the same resource
 * identity, whichever config source supplies the url/token.
 *
 * This file must stay import-light: entrypoints without the full plugin-server env (the
 * recording rasterizer) import it, and anything that evaluates defaultConfig at import
 * would crash them at boot.
 */
export function createOtlpMeterProvider(options: OtlpMeterProviderOptions): MeterProvider {
    return new MeterProvider({
        resource: resourceFromAttributes({
            [ATTR_SERVICE_NAME]: options.serviceName,
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
                    url: options.url,
                    headers: { Authorization: `Bearer ${options.token}` },
                }),
                exportIntervalMillis: options.exportIntervalMillis,
            }),
        ],
    })
}
