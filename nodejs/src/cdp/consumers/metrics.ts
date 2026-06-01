import { Counter, Histogram } from 'prom-client'

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

export const counterHogflowMatcherBytecodeError = new Counter({
    name: 'cdp_hogflow_matcher_bytecode_error',
    help: 'A wait_until_condition or conversion-goal filter threw during evaluation. Filter is treated as non-matching, so the workflow falls through to its timeout branch.',
})

export const counterHogflowMatcherCandidatesEvaluated = new Counter({
    name: 'cdp_hogflow_matcher_candidates_evaluated',
    help: 'Parked hogflow jobs the matcher loaded from cyclotron and evaluated against a batch.',
})

export const counterHogflowMatcherJobsWoken = new Counter({
    name: 'cdp_hogflow_matcher_jobs_woken',
    help: 'Parked hogflow jobs the matcher woke because an incoming event matched.',
})

// Latency of the cyclotron lookup for parked jobs. Watch this for cyclotron-node
// read pressure as the wait-until-event feature ramps.
export const histogramHogflowMatcherFindParkedJobs = new Histogram({
    name: 'cdp_hogflow_matcher_find_parked_jobs_seconds',
    help: 'Duration of the findParkedJobs cyclotron query.',
    buckets: [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
})

export const counterHogflowMatcherEventSkipped = new Counter({
    name: 'cdp_hogflow_matcher_event_skipped',
    help: 'An incoming event was dropped before matching: no identifiers (distinct_id or person_id), or unknown team.',
    labelNames: ['reason'],
})
