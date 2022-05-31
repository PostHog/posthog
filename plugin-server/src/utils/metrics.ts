import { StatsD, Tags } from 'hot-shots'

export async function instrumentQuery<T>(
    statsd: StatsD | undefined,
    metricName: string,
    tag: string | undefined,
    runQuery: () => Promise<T>
): Promise<T> {
    const tags: Tags | undefined = tag ? { queryTag: tag } : undefined
    const timer = new Date()

    statsd?.increment(`${metricName}.total`, tags)
    try {
        return await runQuery()
    } finally {
        statsd?.timing(metricName, timer, tags)
    }
}
