import { Counter } from 'prom-client'

export const counterParseError = new Counter({
    name: 'cdp_function_parse_error',
    help: 'A function invocation was parsed with an error',
    labelNames: ['error'],
})

export const counterRateLimited = new Counter({
    name: 'cdp_function_rate_limited',
    help: 'A function invocation was rate limited',
    labelNames: ['kind', 'function_id'],
})

export const counterHogFunctionStateOnEvent = new Counter({
    name: 'cdp_hog_function_state_on_event',
    help: 'Metric the state of a hog function that matched an event',
    labelNames: ['state', 'kind'],
})

export const counterBatchHogFlowTriggerFailed = new Counter({
    name: 'cdp_batch_hog_flow_trigger_failed',
    help: 'A batch hog flow run failed during audience resolution and was skipped',
    labelNames: ['hog_flow_id', 'reason'],
})

export const counterBatchHogFlowAudienceTruncated = new Counter({
    name: 'cdp_batch_hog_flow_audience_truncated',
    help: 'A batch hog flow run hit the per-team maxAudienceSize cap before finishing the audience',
    labelNames: ['hog_flow_id'],
})

export const counterBatchHogFlowResolverPagesProcessed = new Counter({
    name: 'cdp_batch_hog_flow_resolver_pages_processed',
    help: 'Total pages processed by the cyclotron-based batch resolver',
    labelNames: ['outcome'], // success | fetch_failure | terminal_write_failure
})
