import { Summary } from 'prom-client'

export async function instrumentQuery<T>(
    metricName: string,
    tag: string | undefined,
    runQuery: () => Promise<T>
): Promise<T> {
    return instrument(
        {
            metricName,
            key: 'queryTag',
            tag,
        },
        runQuery
    )
}

export async function instrument<T>(
    options: {
        metricName: string
        key?: string
        tag?: string
        data?: any
    },
    runQuery: () => Promise<T>
): Promise<T> {
    const timer = new Date()
    try {
        return await runQuery()
    } finally {
        instrumentedFnSummary
            .labels(options.metricName, String(options.key ?? 'null'), String(options.tag ?? 'null'))
            .observe(Date.now() - timer.getTime())
    }
}

const instrumentedFnSummary = new Summary({
    name: 'instrumented_fn_duration_ms',
    help: 'Duration of instrumented functions',
    labelNames: ['metricName', 'key', 'tag'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})
