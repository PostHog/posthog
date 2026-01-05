import { Counter } from 'prom-client'

export const counterParseError = new Counter({
    name: 'cdp_function_parse_error',
    help: 'A function invocation was parsed with an error',
    labelNames: ['error'],
})

export const counterQuotaLimited = new Counter({
    name: 'cdp_function_quota_limited',
    help: 'A function invocation was quota limited',
    labelNames: ['team_id'],
})

export const counterRateLimited = new Counter({
    name: 'cdp_function_rate_limited',
    help: 'A function invocation was rate limited',
    labelNames: ['kind'],
})

export const counterHogFunctionStateOnEvent = new Counter({
    name: 'cdp_hog_function_state_on_event',
    help: 'Metric the state of a hog function that matched an event',
    labelNames: ['state', 'kind'],
})
