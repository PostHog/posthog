// Capture routes by the same prefix, so the AI pipeline admits every `$ai_*` event, including
// names it has never seen. The query-routing list in posthog/hogql_queries/ai/ai_table_resolver.py
// stays exact on purpose: ai_events lacks full history for anything but the core types.
export const AI_EVENT_NAME_PREFIX = '$ai_'

export function isAiEventName(event: string): boolean {
    return event.startsWith(AI_EVENT_NAME_PREFIX)
}

// Anything that writes a cost onto an event must gate on this set. A cost on any
// other event type is never priced or labeled by processCost, and the AI
// observability usage report sums $ai_total_cost_usd across every AI event type,
// so a cost on a span is counted a second time.
export const COSTED_AI_EVENT_TYPES = new Set(['$ai_generation', '$ai_embedding', '$ai_evaluation'])
