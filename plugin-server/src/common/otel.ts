import { Attributes, SpanKind, SpanStatusCode, Tracer, trace } from '@opentelemetry/api'
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-grpc'
import { PgInstrumentation } from '@opentelemetry/instrumentation-pg'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { NodeSDK } from '@opentelemetry/sdk-node'
import { ParentBasedSampler, TraceIdRatioBasedSampler } from '@opentelemetry/sdk-trace-node'
import { ATTR_SERVICE_NAME, ATTR_SERVICE_VERSION } from '@opentelemetry/semantic-conventions'

import { defaultConfig } from '~/config/config'
import { logger } from '~/utils/logger'

export const tracer = trace.getTracer('postgres')

function redactSQL(sql: string): string {
    return sql
        .replace(/'(?:''|[^'])*'/g, '?')
        .replace(/\b\d+(?:\.\d+)?\b/g, '?')
        .replace(/\bTRUE|FALSE\b/gi, '?')
}

const pgInstrumentation = new PgInstrumentation({
    // capture text + values (we'll redact below)
    enhancedDatabaseReporting: true,
    requireParentSpan: false,
    requestHook: (span, info) => {
        // info.query?: { text?: string; values?: any[] }
        const sql = info?.query?.text
        if (sql) {
            span.setAttribute('db.statement.redacted', redactSQL(sql))
        }
        const count = info?.query?.values?.length ?? 0
        span.setAttribute('db.param_count', count)
    },
    responseHook: (span, info) => {
        // info.result?: { rowCount?: number }
        const rows = info?.data.rowCount
        if (typeof rows === 'number') {
            span.setAttribute('db.postgresql.row_count', rows)
        }
    },
})

// W3C is default; keep it for header interop
const sdk = new NodeSDK({
    resource: resourceFromAttributes({
        [ATTR_SERVICE_NAME]: `node-${defaultConfig.PLUGIN_SERVER_MODE ?? 'plugin-server'}`,
        [ATTR_SERVICE_VERSION]: process.env.COMMIT_SHA ?? 'dev',
    }),
    traceExporter: new OTLPTraceExporter({
        url: defaultConfig.OTEL_EXPORTER_OTLP_ENDPOINT,
    }),
    instrumentations: [getNodeAutoInstrumentations(), pgInstrumentation],
    sampler: new ParentBasedSampler({
        root: new TraceIdRatioBasedSampler(defaultConfig.OTEL_TRACES_SAMPLER_ARG),
    }),

    // add your DB/HTTP instrumentations as needed
})

export const initTracing = (): void => {
    if (!defaultConfig.OTEL_SDK_DISABLED && defaultConfig.OTEL_EXPORTER_OTLP_ENDPOINT) {
        logger.info('Starting tracing with endpoint', {
            endpoint: defaultConfig.OTEL_EXPORTER_OTLP_ENDPOINT,
            samplerArg: defaultConfig.OTEL_TRACES_SAMPLER_ARG,
        })
        sdk.start()
    }
}

export function withSpan<T>(
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
