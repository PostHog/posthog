import { StatsD, Tags } from 'hot-shots'

import { runInSpan } from '../init'
import { UUID } from './utils'

type StopCallback = () => void

export function instrumentQuery<T>(
    statsd: StatsD | undefined,
    metricName: string,
    tag: string | undefined,
    runQuery: () => Promise<T>
): Promise<T> {
    return runInSpan(
        {
            op: metricName,
            description: tag,
        },
        async () => {
            const tags: Tags | undefined = tag ? { queryTag: tag } : undefined
            const timer = new Date()

            statsd?.increment(`${metricName}.total`, tags)
            try {
                return await runQuery()
            } finally {
                statsd?.timing(metricName, timer, tags)
            }
        }
    )
}

export function captureEventLoopMetrics(statsd: StatsD, instanceId: UUID): StopCallback {
    const timer = setInterval(() => {
        const time = new Date()
        setTimeout(() => {
            statsd?.timing('event_loop_lag_set_timeout', time, {
                instanceId: instanceId.toString(),
            })
        }, 0)
    }, 2000)

    return () => {
        clearInterval(timer)
    }
}
