import { SAMPLE_PODS, type SampleAttributeRow } from './sampleInfra'

export interface SampleSpanGroup {
    service: string
    name: string
    root: boolean
    count: number
    errorRate: number
    medianMs: number
    attributes: Record<string, string>
}

const http = (method: string, route: string): Record<string, string> => ({
    'http.method': method,
    'http.route': route,
    'span.kind': 'server',
})
const database = (system: string, operation: string): Record<string, string> => ({
    'db.system': system,
    'db.operation': operation,
    'span.kind': 'client',
})
const messaging = (operation: string, destination: string): Record<string, string> => ({
    'messaging.system': 'kafka',
    'messaging.operation': operation,
    'messaging.destination': destination,
    'span.kind': operation === 'publish' ? 'producer' : 'consumer',
})

const group = (
    service: string,
    name: string,
    count: number,
    medianMs: number,
    errorRate: number,
    attributes: Record<string, string>
): SampleSpanGroup => ({
    service,
    name,
    root: attributes['span.kind'] === 'server' || attributes['span.kind'] === 'consumer',
    count,
    errorRate,
    medianMs,
    attributes,
})

export const SAMPLE_SPANS: SampleSpanGroup[] = [
    group('api', 'POST /api/projects/:id/query', 48_200, 180, 0.018, http('POST', '/api/projects/:id/query')),
    group('api', 'GET /api/projects/:id/insights', 31_700, 85, 0.006, http('GET', '/api/projects/:id/insights')),
    group('api', 'GET /api/projects/:id/dashboards', 19_400, 62, 0.004, http('GET', '/api/projects/:id/dashboards')),
    group('api', 'postgres SELECT', 142_600, 6, 0.001, database('postgresql', 'SELECT')),
    group('api', 'clickhouse SELECT', 51_300, 140, 0.021, database('clickhouse', 'SELECT')),
    group('api', 'redis GET', 96_800, 1.5, 0.0005, database('redis', 'GET')),
    group('web', 'GET /', 27_900, 34, 0.002, http('GET', '/')),
    group('web', 'GET /pricing', 8_600, 41, 0.002, http('GET', '/pricing')),
    group('web', 'GET /docs/:slug', 12_300, 58, 0.009, http('GET', '/docs/:slug')),
    group('auth', 'POST /login', 9_100, 120, 0.034, http('POST', '/login')),
    group('auth', 'token.verify', 88_400, 3, 0.002, { 'span.kind': 'internal' }),
    group('auth', 'postgres SELECT', 17_800, 5, 0.001, database('postgresql', 'SELECT')),
    group('checkout', 'POST /checkout/session', 2_480, 420, 0.047, http('POST', '/checkout/session')),
    group('checkout', 'stripe.charges.create', 2_310, 680, 0.052, { 'peer.service': 'stripe', 'span.kind': 'client' }),
    group('checkout', 'postgres INSERT', 4_900, 9, 0.003, database('postgresql', 'INSERT')),
    group('ingest', 'POST /capture', 412_000, 12, 0.003, http('POST', '/capture')),
    group('ingest', 'kafka publish events_ingestion', 409_500, 4, 0.002, messaging('publish', 'events_ingestion')),
    group('worker', 'kafka process events_ingestion', 398_700, 28, 0.004, messaging('process', 'events_ingestion')),
    group('worker', 'clickhouse INSERT', 6_200, 950, 0.012, database('clickhouse', 'INSERT')),
    group('worker', 'export.render', 1_150, 3_800, 0.061, { 'export.format': 'png', 'span.kind': 'internal' }),
    group('worker', 'kafka process exports', 1_180, 4_200, 0.064, messaging('process', 'exports')),
    group('worker', 's3 PutObject', 1_420, 210, 0.008, { 'rpc.service': 'S3', 'span.kind': 'client' }),
]

export function spanResourceAttributes(service: string): Record<string, string> {
    const pod = SAMPLE_PODS.find((candidate) => candidate.service === service)
    return {
        'service.name': service,
        'deployment.environment.name': 'production',
        'k8s.namespace.name': pod?.namespace ?? 'default',
        'k8s.deployment.name': service,
        'service.version': pod?.version ?? '1.0.0',
    }
}

export const SAMPLE_TRACE_ATTRIBUTES: SampleAttributeRow[] = SAMPLE_SPANS.flatMap((span) => {
    const base = { service: span.service, level: '', resource: span.service, count: span.count }
    return [
        ...Object.entries(spanResourceAttributes(span.service)).map(([key, value]) => ({
            ...base,
            isResource: true,
            key,
            value,
        })),
        { ...base, isResource: false, key: 'name', value: span.name },
        ...Object.entries(span.attributes).map(([key, value]) => ({ ...base, isResource: false, key, value })),
    ]
})
