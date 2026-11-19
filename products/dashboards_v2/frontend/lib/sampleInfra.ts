export interface SamplePod {
    service: string
    pod: string
    namespace: string
    node: string
    region: string
    version: string
    environment: string
}

export interface SampleAttributeRow {
    service: string
    level: string
    resource: string
    isResource: boolean
    key: string
    value: string
    count: number
}

export type Weighted = [value: string, weight: number][]

const REGIONS = ['us-east-1', 'eu-central-1', 'ap-southeast-2']
const POD_SUFFIXES = ['x2kq7', 'm8tzc', 'p4vnd', 'h7cdw']
const WORKLOADS = [
    { service: 'api', namespace: 'app', hash: '6c9d7f5b8', pods: 4, version: '2.41.0' },
    { service: 'web', namespace: 'app', hash: '85f6bd4c7', pods: 3, version: '2.41.0' },
    { service: 'auth', namespace: 'app', hash: '5d8c9f7b6', pods: 2, version: '1.18.3' },
    { service: 'checkout', namespace: 'payments', hash: '7b5f9d6c4', pods: 2, version: '3.7.1' },
    { service: 'ingest', namespace: 'pipeline', hash: '9f7c6d8b5', pods: 4, version: '5.2.0' },
    { service: 'worker', namespace: 'pipeline', hash: '64d9b8f7c', pods: 3, version: '5.2.0' },
]

export const SAMPLE_PODS: SamplePod[] = WORKLOADS.flatMap((workload) =>
    POD_SUFFIXES.slice(0, workload.pods).map((suffix, index) => {
        const region = REGIONS[index % REGIONS.length]
        return {
            service: workload.service,
            pod: `${workload.service}-${workload.hash}-${suffix}`,
            namespace: workload.namespace,
            node: `node-${region}-${(index % 2) + 1}`,
            region,
            version: workload.version,
            environment: workload.pods > 2 && index === workload.pods - 1 ? 'staging' : 'production',
        }
    })
)

export const SAMPLE_SERVICES = WORKLOADS.map((workload) => workload.service)

export function sampleFraction(seed: string): number {
    let hash = 2166136261
    for (let index = 0; index < seed.length; index++) {
        hash = Math.imul(hash ^ seed.charCodeAt(index), 16777619)
    }
    return (hash >>> 0) / 4294967296
}

export function portions(values: Weighted): [value: string, portion: number][] {
    const total = values.reduce((sum, [, weight]) => sum + weight, 0)
    return values.map(([value, weight]) => [value, total ? weight / total : 0])
}
