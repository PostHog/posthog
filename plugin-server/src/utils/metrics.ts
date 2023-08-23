import { StatsD, Tags } from 'hot-shots'
import { Histogram } from 'prom-client'

import { runInSpan } from '../sentry'
import { UUID } from './utils'

type StopCallback = () => void

export function instrumentQuery<T>(
    statsd: StatsD | undefined,
    metricName: string,
    tag: string | undefined,
    runQuery: () => Promise<T>
): Promise<T> {
    const end = dataStoreQueryDuration
        .labels({
            query: metricName,
            tag: tag ?? 'null',
        })
        .startTimer()
    const result = instrument(
        statsd,
        {
            metricName,
            key: 'queryTag',
            tag,
        },
        runQuery
    )
    end()
    return result
}

export function instrument<T>(
    statsd: StatsD | undefined,
    options: {
        metricName: string
        key?: string
        tag?: string
        tags?: Tags
        data?: any
    },
    runQuery: () => Promise<T>
): Promise<T> {
    const tags: Tags | undefined = options.key ? { ...options.tags, [options.key]: options.tag! } : options.tags
    return runInSpan(
        {
            op: options.metricName,
            description: options.tag,
            data: { ...tags, ...options.data },
        },
        async () => {
            const timer = new Date()
            statsd?.increment(`${options.metricName}.total`, tags)
            try {
                return await runQuery()
            } finally {
                statsd?.timing(options.metricName, timer, tags)
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

export const dataStoreQueryDuration = new Histogram({
    name: 'data_store_query_duration',
    help: 'Query latency to data stores, per query and tag',
    labelNames: ['query', 'tag'],
})
