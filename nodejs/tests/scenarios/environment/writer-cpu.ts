import type { Aws } from '../cloud/aws'
import type { RunManifest } from '../cloud/lease'
import type { CpuPoint } from '../judge/bars'
import type { DriveWindow } from '../judge/measurements'

const MINUTE_MS = 60_000

type CpuData = { MetricDataResults: { Timestamps: string[]; Values: number[]; StatusCode?: string }[] }

export async function writerCpuOf(
    aws: Aws,
    manifest: RunManifest,
    { startedAt, endedAt }: DriveWindow
): Promise<CpuPoint[]> {
    const query = {
        Id: 'cpu',
        MetricStat: {
            Metric: {
                Namespace: 'AWS/RDS',
                MetricName: 'CPUUtilization',
                Dimensions: [
                    { Name: 'DBClusterIdentifier', Value: manifest.stackName },
                    { Name: 'Role', Value: 'WRITER' },
                ],
            },
            Period: 60,
            Stat: 'Maximum',
        },
    }
    const { MetricDataResults } = (await aws.call([
        'cloudwatch',
        'get-metric-data',
        '--metric-data-queries',
        JSON.stringify([query]),
        '--start-time',
        new Date(startedAt - (startedAt % MINUTE_MS)).toISOString(),
        '--end-time',
        new Date(Math.ceil(endedAt / MINUTE_MS) * MINUTE_MS).toISOString(),
    ])) as CpuData
    const [{ Timestamps, Values, StatusCode }] = MetricDataResults
    if (StatusCode !== undefined && StatusCode !== 'Complete') {
        throw new Error(`the writer CPU read came back ${StatusCode}, not Complete`)
    }
    return Timestamps.map((at, i) => ({ at: Date.parse(at), percent: Values[i] })).sort((a, b) => a.at - b.at)
}
