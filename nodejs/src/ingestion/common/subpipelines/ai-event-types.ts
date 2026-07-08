// AI event type names, shared by the ai lane and the ingestion steps that route AI events.
// Canonical Node.js list. Python mirror: posthog/hogql_queries/ai/ai_table_resolver.py
export const AI_EVENT_TYPES = new Set([
    '$ai_generation',
    '$ai_embedding',
    '$ai_evaluation',
    '$ai_span',
    '$ai_trace',
    '$ai_metric',
    '$ai_feedback',
])
