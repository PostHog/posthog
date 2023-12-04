import { StatsD, Tags } from 'hot-shots'
import { Summary } from 'prom-client'

import { runInSpan } from '../sentry'
import { UUID } from './utils'

type StopCallback = () => void

export function instrumentQuery<T>(
    statsd: StatsD | undefined,
    metricName: string,
    tag: string | undefined,
    runQuery: () => Promise<T>
): Promise<T> {
    return instrument(
        statsd,
        {
            metricName,
            key: 'queryTag',
            tag,
        },
        runQuery
    )
}

export function instrument<T>(
    statsd: StatsD | undefined,
    options: {
        metricName: string
        key?: string
        tag?: string
        data?: any
    },
    runQuery: () => Promise<T>
): Promise<T> {
    const tags: Tags = options.key ? { [options.key]: options.tag! } : {}
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
                instrumentedFnSummary
                    .labels(options.metricName, String(options.key ?? 'null'), String(options.tag ?? 'null'))
                    .observe(Date.now() - timer.getTime())
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

const instrumentedFnSummary = new Summary({
    name: 'instrumented_fn_duration_ms',
    help: 'Duration of instrumented functions',
    labelNames: ['metricName', 'key', 'tag'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})
