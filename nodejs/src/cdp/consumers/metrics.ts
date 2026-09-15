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

// An event that matched a function but produced no invocation. Counted here as well as in the
// per-function app metrics, because only a fleet-wide series separates one customer's broken
// config from a platform bug that breaks every function using one builtin.
//
// Incremented at the two build-time call sites rather than inside filterFunctionInstrumented,
// which also runs mid-execution for conditional branches and would inflate this.
export const counterInvocationBuildFailures = new Counter({
    name: 'cdp_invocation_build_failures_total',
    help: 'An event matched a function but no invocation could be built for it',
    labelNames: ['step', 'function_type'],
})
