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
    help: 'AI cost modality token extraction outcomes by source',
    labelNames: ['status', 'source'],
})

export const aiCostTotalOutcomeCounter = new Counter({
    name: 'llma_ai_cost_outcome_total',
    help: 'Outcome of total cost calculation (positive, zero, negative)',
    labelNames: ['outcome'],
})

export const aiToolCallExtractionCounter = new Counter({
    name: 'llma_ai_tool_call_extraction_total',
    help: 'AI tool call extraction outcomes',
    labelNames: ['status'],
})

export const aiOtelMiddlewareCounter = new Counter({
    name: 'llma_ai_otel_middleware_total',
    help: 'OTel events processed by library middleware',
    labelNames: ['library'],
})

export const aiOtelEventTypeCounter = new Counter({
    name: 'llma_ai_otel_event_type_total',
    help: 'OTel events by type and library',
    labelNames: ['event_type', 'library'],
})

export const aiOtelOlderSpecEventsCounter = new Counter({
    name: 'llma_ai_otel_older_spec_events_total',
    help: 'Outcome of decoding the older OTel GenAI span-events `events` attribute',
    labelNames: ['outcome'],
})
