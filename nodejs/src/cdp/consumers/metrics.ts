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

export const counterTeamIdSource = new Counter({
    name: 'cdp_events_team_id_source',
    help: 'Where the consumer read an event team id from. "body" means the message carried no usable team id header, so the consumer parsed the event to find one.',
    labelNames: ['source'],
})

export const counterTeamIdHeaderMismatch = new Counter({
    name: 'cdp_events_team_id_header_mismatch',
    help: 'An event body named a different team than its header. The event is parked, because the two teams would send one team data to another team destinations.',
})

export const counterUnmatchedEventName = new Counter({
    name: 'cdp_events_unmatched_event_name',
    help: 'Events whose name no destination or workflow of their team admits. "skipped" is false while CDP_EVENTS_SKIP_UNMATCHED_EVENT_NAMES is off and the consumer still parses them.',
    labelNames: ['skipped'],
})

export const counterUnmatchedEventNameInvoked = new Counter({
    name: 'cdp_events_unmatched_event_name_invoked',
    help: 'Events the name gate rejected that a destination or workflow still invoked once parsed. Counted while CDP_EVENTS_SKIP_UNMATCHED_EVENT_NAMES is off. Each one is an event the skip would drop, so it must stay at zero before the switch goes on. It counts only invocations that survive the watcher, rate limits, quotas and masking, so a wrong rejection for a disabled or limited destination does not show.',
})
