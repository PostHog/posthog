import { performance } from 'perf_hooks'
import { Summary } from 'prom-client'

const jsonParseDurationMsSummary = new Summary({
    name: 'json_parse_duration_ms',
    help: 'Time to parse JSON using different methods',
    labelNames: ['method'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export function parseJSON(json: string) {
    const startTime = performance.now()
    // eslint-disable-next-line no-restricted-syntax
    const result = JSON.parse(json)
    jsonParseDurationMsSummary.labels('native').observe(performance.now() - startTime)

    return result
}
