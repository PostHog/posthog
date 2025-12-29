import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-grpc'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { NodeSDK } from '@opentelemetry/sdk-node'
import { ParentBasedSampler, TraceIdRatioBasedSampler } from '@opentelemetry/sdk-trace-node'
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from '@opentelemetry/semantic-conventions'

import { defaultConfig } from '~/config/config'
import { registerShutdownHandler } from '~/lifecycle'
import { logger } from '~/utils/logger'

import { CappedSiblingsExporter } from './config/capped-siblings-exporter'

let sdk: NodeSDK | null = null

export const initTracing = (): void => {
    if (defaultConfig.OTEL_SDK_DISABLED || !defaultConfig.OTEL_EXPORTER_OTLP_ENDPOINT) {
        return
    }

    logger.info('Starting tracing with endpoint', {
        endpoint: defaultConfig.OTEL_EXPORTER_OTLP_ENDPOINT,
        samplerArg: defaultConfig.OTEL_TRACES_SAMPLER_ARG,
    })

    const baseExporter = new OTLPTraceExporter({
        url: defaultConfig.OTEL_EXPORTER_OTLP_ENDPOINT,
    })

    const traceExporter = new CappedSiblingsExporter(baseExporter, {
        maxPerGroup: defaultConfig.OTEL_MAX_SPANS_PER_GROUP, // keep 2 siblings per (traceId,parent,name)
        minDurationMs: defaultConfig.OTEL_MIN_SPAN_DURATION_MS, // always keep >=50ms
    })

    sdk = new NodeSDK({
        resource: resourceFromAttributes({
            [ATTR_SERVICE_NAME]: `node-${defaultConfig.PLUGIN_SERVER_MODE ?? 'plugin-server'}`,
            [ATTR_SERVICE_VERSION]: process.env.COMMIT_SHA ?? 'dev',
        }),
        traceExporter,
        instrumentations: [getNodeAutoInstrumentations()],
        sampler: new ParentBasedSampler({
            root: new TraceIdRatioBasedSampler(defaultConfig.OTEL_TRACES_SAMPLER_ARG),
        }),
    })
    sdk.start()
}

registerShutdownHandler(async () => {
    if (!sdk) {
        return
    }

    await sdk.shutdown()
})
