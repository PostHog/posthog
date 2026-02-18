import { Counter } from 'prom-client'

export const aiCostLookupCounter = new Counter({
    name: 'llma_ai_cost_lookup_total',
    help: 'AI model cost lookup outcomes',
    labelNames: ['status'],
})

export const aiErrorNormalizationCounter = new Counter({
    name: 'llma_ai_error_normalization_total',
    help: 'AI error normalization outcomes',
    labelNames: ['status'],
})

export const aiCostModalityExtractionCounter = new Counter({
    name: 'llma_ai_cost_modality_extraction_total',
    help: 'AI cost modality token extraction outcomes',
    labelNames: ['status'],
})

export const aiCostTotalOutcomeCounter = new Counter({
    name: 'llma_ai_cost_total_outcome',
    help: 'Outcome of total cost calculation (positive, zero, negative)',
    labelNames: ['outcome'],
})
