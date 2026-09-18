// An event belongs to the AI lane iff its name starts with this prefix. Capture routes by
// the same rule, so the AI pipeline admits and enriches every `$ai_*` event, including
// names it has never seen. The Python query-routing list in
// posthog/hogql_queries/ai/ai_table_resolver.py intentionally stays exact: ai_events lacks
// full history for anything but the core types, so their queries stay on the shared events
// table to avoid the resolver misreading the missing rows as expired data.
export const AI_EVENT_NAME_PREFIX = '$ai_'

export function isAiEventName(event: string): boolean {
    return event.startsWith(AI_EVENT_NAME_PREFIX)
}

// Exact names the analytics-lane usage records bill under the AI key. Only billing reads
// this; ingestion routes and enriches by `isAiEventName`.
export const AI_EVENT_TYPES = new Set([
    '$ai_generation',
    '$ai_embedding',
    '$ai_evaluation',
    '$ai_span',
    '$ai_trace',
    '$ai_metric',
    '$ai_feedback',
    '$ai_tag',
    '$ai_generation_summary',
    '$ai_trace_summary',
    '$ai_evaluation_report',
])

// Anything that writes a cost onto an event must gate on this set. A cost on any
// other event type is never priced or labeled by processCost, and the AI
// observability usage report sums $ai_total_cost_usd across every AI event type,
// so a cost on a span is counted a second time.
export const COSTED_AI_EVENT_TYPES = new Set(['$ai_generation', '$ai_embedding', '$ai_evaluation'])
