import {
    portions,
    SAMPLE_PODS,
    sampleFraction,
    type SampleAttributeRow,
    type SamplePod,
    type Weighted,
} from './sampleInfra'

const LINES_PER_HOUR: Record<string, number> = {
    api: 42_600,
    web: 18_300,
    auth: 9_100,
    checkout: 6_400,
    ingest: 95_800,
    worker: 27_500,
}
const LEVELS: Weighted = [
    ['info', 0.86],
    ['warn', 0.08],
    ['error', 0.035],
    ['debug', 0.025],
]
const ERROR_RATE: Record<string, number> = { checkout: 3.2, worker: 1.8, ingest: 0.4 }

const HTTP_SERVICES = ['api', 'web', 'auth', 'checkout']
const JOB_SERVICES = ['ingest', 'worker']

interface LogAttribute {
    key: string
    coverage: number
    values: Weighted
    services?: string[]
    levels?: string[]
}

const LOG_ATTRIBUTES: LogAttribute[] = [
    {
        key: 'logger.name',
        coverage: 0.96,
        values: [
            ['http.server', 44],
            ['jobs.runner', 21],
            ['kafka.consumer', 17],
            ['db.pool', 12],
            ['auth.session', 6],
        ],
    },
    {
        key: 'http.method',
        coverage: 0.72,
        services: HTTP_SERVICES,
        values: [
            ['GET', 62],
            ['POST', 30],
            ['PUT', 5],
            ['DELETE', 3],
        ],
    },
    {
        key: 'http.status_code',
        coverage: 0.72,
        services: HTTP_SERVICES,
        values: [
            ['200', 78],
            ['201', 6],
            ['302', 4],
            ['404', 4],
            ['400', 3],
            ['401', 3],
            ['500', 2],
        ],
    },
    {
        key: 'http.route',
        coverage: 0.7,
        services: HTTP_SERVICES,
        values: [
            ['/api/projects/:id/query', 30],
            ['/api/projects/:id/insights', 22],
            ['/healthz', 19],
            ['/api/projects/:id/dashboards', 14],
            ['/login', 9],
            ['/checkout/session', 6],
        ],
    },
    {
        key: 'queue.name',
        coverage: 0.64,
        services: JOB_SERVICES,
        values: [
            ['ingestion', 55],
            ['exports', 14],
            ['webhooks', 13],
            ['emails', 9],
            ['billing', 5],
            ['cleanup', 4],
        ],
    },
    {
        key: 'kafka.topic',
        coverage: 0.5,
        services: JOB_SERVICES,
        values: [
            ['events_ingestion', 70],
            ['session_recordings', 20],
            ['exports', 10],
        ],
    },
    {
        key: 'error.type',
        coverage: 0.9,
        levels: ['error'],
        values: [
            ['TimeoutError', 38],
            ['ValidationError', 24],
            ['ConnectionResetError', 19],
            ['RateLimitExceeded', 12],
            ['KeyError', 7],
        ],
    },
]

const resourceAttributes = (pod: SamplePod): [key: string, value: string][] => [
    ['service.name', pod.service],
    ['deployment.environment.name', pod.environment],
    ['k8s.namespace.name', pod.namespace],
    ['k8s.deployment.name', pod.service],
    ['k8s.pod.name', pod.pod],
    ['k8s.node.name', pod.node],
    ['cloud.region', pod.region],
    ['service.version', pod.version],
]

function podRows(pod: SamplePod): SampleAttributeRow[] {
    const replicas = SAMPLE_PODS.filter((other) => other.service === pod.service).length
    const podLines = ((LINES_PER_HOUR[pod.service] ?? 1000) / replicas) * (0.8 + 0.4 * sampleFraction(pod.pod))
    return LEVELS.flatMap(([level, share]) => {
        const lines = Math.round(podLines * share * (level === 'error' ? (ERROR_RATE[pod.service] ?? 1) : 1))
        const base = { service: pod.service, level, resource: pod.pod }
        const resource = resourceAttributes(pod).map(([key, value]) => ({
            ...base,
            isResource: true,
            key,
            value,
            count: lines,
        }))
        const line = LOG_ATTRIBUTES.filter(
            (attribute) =>
                (!attribute.services || attribute.services.includes(pod.service)) &&
                (!attribute.levels || attribute.levels.includes(level))
        ).flatMap((attribute) =>
            portions(attribute.values).map(([value, portion]) => ({
                ...base,
                isResource: false,
                key: attribute.key,
                value,
                count: Math.round(lines * attribute.coverage * portion),
            }))
        )
        return [...resource, ...line].filter((row) => row.count > 0)
    })
}

export const SAMPLE_LOG_ATTRIBUTES: SampleAttributeRow[] = SAMPLE_PODS.flatMap(podRows)
