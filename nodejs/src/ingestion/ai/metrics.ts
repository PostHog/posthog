import { Counter } from 'prom-client'

export const aiCostLookupCounter = new Counter({
    name: 'ai_cost_lookup_total',
    help: 'AI model cost lookup outcomes',
    labelNames: ['status'],
})

export const aiErrorNormalizationCounter = new Counter({
    name: 'ai_error_normalization_total',
    help: 'AI error normalization outcomes',
    labelNames: ['status'],
})
