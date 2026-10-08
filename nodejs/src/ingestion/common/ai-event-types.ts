// Capture routes on this prefix too, so any `$ai_*` name is admitted here. The query-routing
// list in posthog/hogql_queries/ai/ai_table_resolver.py stays exact: ai_events lacks history
// for anything but the core types.
export const AI_EVENT_NAME_PREFIX = '$ai_'

export function isAiEventName(event: string): boolean {
    return event.startsWith(AI_EVENT_NAME_PREFIX)
}

// Anything that writes a cost onto an event must gate on this set. A cost on any
// other event type is never priced or labeled by processCost, and the AI
// observability usage report sums $ai_total_cost_usd across every AI event type,
// so a cost on a span is counted a second time.
export const COSTED_AI_EVENT_TYPES = new Set(['$ai_generation', '$ai_embedding', '$ai_evaluation'])
