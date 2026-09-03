// AI event type names accepted by the ai lane.
// The Python query-routing list in posthog/hogql_queries/ai/ai_table_resolver.py
// intentionally lists only the core types: ai_events lacks full history for the
// meta-events, so their queries must stay on the shared events table to avoid the
// resolver misreading the missing rows as expired data.
export const AI_EVENT_TYPES = new Set([
    // Core AI telemetry, enriched by process-ai-event.ts (costs, model params, tool calls).
    '$ai_generation',
    '$ai_embedding',
    '$ai_evaluation',
    '$ai_span',
    '$ai_trace',
    '$ai_metric',
    '$ai_feedback',
    // Internal meta-events emitted about AI telemetry (taggers, summarization, eval
    // reports). Cost and model-param enrichment gates on the exact core names above,
    // so these only get trace-property normalization and the ai_events double-write.
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
