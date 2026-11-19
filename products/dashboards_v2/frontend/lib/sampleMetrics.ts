import { SAMPLE_PODS, sampleFraction, type SamplePod } from './sampleInfra'

export type SampleLabels = Record<string, string>
type Dimension = SampleLabels[]

const each = (label: string, values: string[]): Dimension => values.map((value) => ({ [label]: value }))

function distinct(rows: SampleLabels[]): Dimension {
    const seen = new Map<string, SampleLabels>()
    for (const row of rows) {
        seen.set(JSON.stringify(row), row)
    }
    return [...seen.values()]
}

const pods = (...labels: (keyof SamplePod)[]): Dimension =>
    distinct(SAMPLE_PODS.map((pod) => Object.fromEntries(labels.map((label) => [label, pod[label]]))))

const BUCKETS = each('le', ['0.005', '0.01', '0.025', '0.05', '0.1', '0.25', '0.5', '1', '2.5', '5', '10', '+Inf'])
const METHODS = each('method', ['GET', 'POST', 'PUT', 'DELETE'])
const STATUSES = each('status', ['200', '201', '204', '400', '401', '404', '429', '500', '503'])
const OUTCOMES = each('status', ['ok', 'error'])
const QUEUES = each('queue', ['ingestion', 'exports', 'webhooks', 'emails', 'billing', 'cleanup'])
const JOB_STATUSES = each('status', ['success', 'failed', 'retried'])
const DATABASE_CALLERS = each('service', ['api', 'auth', 'checkout', 'ingest', 'worker'])
const QUEUE_CONSUMERS = each('service', ['worker', 'ingest'])
const OPERATIONS: Dimension = [
    { db: 'postgres', operation: 'select' },
    { db: 'postgres', operation: 'insert' },
    { db: 'postgres', operation: 'update' },
    { db: 'postgres', operation: 'delete' },
    { db: 'clickhouse', operation: 'select' },
    { db: 'clickhouse', operation: 'insert' },
    { db: 'redis', operation: 'get' },
    { db: 'redis', operation: 'set' },
]
const POOLS: Dimension = [
    { db: 'postgres', pool: 'primary' },
    { db: 'postgres', pool: 'replica' },
    { db: 'clickhouse', pool: 'online' },
    { db: 'clickhouse', pool: 'offline' },
    { db: 'redis', pool: 'cache' },
]
const CONTAINERS: Dimension = SAMPLE_PODS.flatMap((pod) =>
    [pod.service, 'envoy'].map((container) => ({
        namespace: pod.namespace,
        pod: pod.pod,
        container,
        node: pod.node,
    }))
)
const NODES: Dimension = pods('node', 'region').map((node, index) => ({
    ...node,
    instance_type: index % 2 ? 'm6i.2xlarge' : 'c6i.4xlarge',
}))
const JOBS: Dimension = SAMPLE_PODS.map((pod) => ({ job: pod.service, instance: `${pod.pod}:9090` }))

const METRICS: Record<string, { dimensions: Dimension[]; keep?: number }> = {
    http_requests_total: { dimensions: [pods('service', 'pod', 'region'), METHODS, STATUSES], keep: 0.45 },
    http_request_duration_seconds_bucket: { dimensions: [pods('service', 'region'), METHODS, BUCKETS] },
    http_request_duration_seconds_count: { dimensions: [pods('service', 'region'), METHODS] },
    http_request_duration_seconds_sum: { dimensions: [pods('service', 'region'), METHODS] },
    http_requests_in_flight: { dimensions: [pods('service', 'pod', 'region')] },
    db_queries_total: { dimensions: [DATABASE_CALLERS, OPERATIONS, OUTCOMES], keep: 0.7 },
    db_query_duration_seconds_bucket: { dimensions: [DATABASE_CALLERS, OPERATIONS, BUCKETS], keep: 0.7 },
    db_connections_active: { dimensions: [DATABASE_CALLERS, POOLS], keep: 0.8 },
    queue_jobs_processed_total: { dimensions: [QUEUES, QUEUE_CONSUMERS, JOB_STATUSES], keep: 0.75 },
    queue_depth: { dimensions: [QUEUES, QUEUE_CONSUMERS], keep: 0.75 },
    queue_job_duration_seconds_bucket: { dimensions: [QUEUES, BUCKETS] },
    container_cpu_usage_seconds_total: { dimensions: [CONTAINERS] },
    container_memory_working_set_bytes: { dimensions: [CONTAINERS] },
    node_cpu_utilization: { dimensions: [NODES, each('mode', ['user', 'system', 'iowait', 'idle'])] },
    node_memory_available_bytes: { dimensions: [NODES] },
    process_resident_memory_bytes: { dimensions: [pods('service', 'pod')] },
    up: { dimensions: [JOBS] },
}

export const SAMPLE_METRIC_NAMES = Object.keys(METRICS).sort()

const series = new Map<string, SampleLabels[]>()

export function sampleSeries(metric: string): SampleLabels[] {
    const definition = METRICS[metric]
    if (!definition) {
        return []
    }
    let rows = series.get(metric)
    if (!rows) {
        rows = definition.dimensions
            .reduce<SampleLabels[]>(
                (combined, dimension) => combined.flatMap((row) => dimension.map((labels) => ({ ...row, ...labels }))),
                [{}]
            )
            .filter(
                ({ le: _bucket, ...labels }) => sampleFraction(metric + JSON.stringify(labels)) < (definition.keep ?? 1)
            )
        series.set(metric, rows)
    }
    return rows
}
