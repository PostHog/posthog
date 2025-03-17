import { performance } from 'perf_hooks'
import { Summary } from 'prom-client'
import { parse as simdjson_parse } from 'simdjson'

import { defaultConfig } from '../config/config'

const jsonParseDurationMsSummary = new Summary({
    name: 'json_parse_duration_ms',
    help: 'Time to parse JSON using different methods',
    labelNames: ['method'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export function parseJSON(json: string) {
    const startTime = performance.now()
    let result

    if (defaultConfig.USE_SIMD_JSON_PARSE) {
        result = simdjson_parse(json)
        jsonParseDurationMsSummary.labels('simd').observe(performance.now() - startTime)
        return result
    }
    // eslint-disable-next-line no-restricted-syntax
    result = JSON.parse(json)
    jsonParseDurationMsSummary.labels('native').observe(performance.now() - startTime)

    // Compare both methods when flag is enabled
    if (defaultConfig.USE_SIMD_JSON_PARSE_FOR_COMPARISON) {
        const simdStartTime = performance.now()
        simdjson_parse(json)
        jsonParseDurationMsSummary.labels('simd').observe(performance.now() - simdStartTime)
    }

    return result
}
