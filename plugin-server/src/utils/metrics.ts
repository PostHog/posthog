import { StatsD, Tags } from 'hot-shots'

import { UUID } from './utils'

type StopCallback = () => void

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

export function captureEventLoopMetrics(statsd: StatsD, instanceId: UUID): StopCallback {
    const eventLoopLagInterval = setInterval(() => {
        const time = new Date()
        setImmediate(() => {
            statsd?.timing('event_loop_lag', time, {
                instanceId: instanceId.toString(),
            })
        })
    }, 2000)
    const eventLoopLagSetTimeoutInterval = setInterval(() => {
        const time = new Date()
        setTimeout(() => {
            statsd?.timing('event_loop_lag_set_timeout', time, {
                instanceId: instanceId.toString(),
            })
        }, 0)
    }, 2000)

    return () => {
        clearInterval(eventLoopLagInterval)
        clearInterval(eventLoopLagSetTimeoutInterval)
    }
}
