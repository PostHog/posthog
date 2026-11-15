import type { Aws } from '../cloud/aws'
import type { RunManifest } from '../cloud/lease'
import type { CpuPoint } from '../judge/bars'
import type { DriveWindow } from '../judge/measurements'

const MINUTE_MS = 60_000
const POLL_MS = 30_000
const PUBLISH_WAIT_MS = 5 * MINUTE_MS

type CpuData = { MetricDataResults: { Timestamps: string[]; Values: number[]; StatusCode?: string }[] }

export async function writerCpuOf(
    aws: Aws,
    manifest: RunManifest,
    window: DriveWindow,
    signal?: AbortSignal
): Promise<CpuPoint[]> {
    const lastMinute = Math.floor(window.endedAt / MINUTE_MS) * MINUTE_MS - MINUTE_MS
    const expired = new AbortController()
    const timer = setTimeout(() => expired.abort(), PUBLISH_WAIT_MS)
    const stop = signal ? AbortSignal.any([signal, expired.signal]) : expired.signal
    let points: CpuPoint[] = []
    try {
        points = await readWriterCpu(aws, manifest, window, stop)
        while (!points.some(({ at }) => at === lastMinute) && !stop.aborted) {
            await pollWait(stop)
            if (stop.aborted) {
                break
            }
            points = await readWriterCpu(aws, manifest, window, stop)
        }
    } catch (error) {
        if (!stop.aborted) {
            throw error
        }
    } finally {
        clearTimeout(timer)
    }
    return points
}

const pollWait = (signal: AbortSignal): Promise<void> =>
    new Promise((resolve) => {
        const done = (): void => {
            clearTimeout(timer)
            signal.removeEventListener('abort', done)
            resolve()
        }
        const timer = setTimeout(done, POLL_MS)
        signal.addEventListener('abort', done, { once: true })
    })

async function readWriterCpu(
    aws: Aws,
    manifest: RunManifest,
    { startedAt, endedAt }: DriveWindow,
    signal: AbortSignal
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
    const { MetricDataResults } = (await aws.call(
        [
            'cloudwatch',
            'get-metric-data',
            '--metric-data-queries',
            JSON.stringify([query]),
            '--start-time',
            new Date(startedAt - (startedAt % MINUTE_MS)).toISOString(),
            '--end-time',
            new Date(Math.ceil(endedAt / MINUTE_MS) * MINUTE_MS).toISOString(),
        ],
        signal
    )) as CpuData
    const [{ Timestamps, Values, StatusCode }] = MetricDataResults
    if (StatusCode !== undefined && StatusCode !== 'Complete') {
        throw new Error(`the writer CPU read came back ${StatusCode}, not Complete`)
    }
    return Timestamps.map((at, i) => ({ at: Date.parse(at), percent: Values[i] })).sort((a, b) => a.at - b.at)
}
