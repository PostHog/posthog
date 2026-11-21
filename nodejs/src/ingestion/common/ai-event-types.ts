// Capture routes on this prefix too, so any `$ai_*` name is admitted here. The query-routing
// list in posthog/hogql_queries/ai/ai_table_resolver.py stays exact: ai_events lacks history
// for anything but the core types.
export const AI_EVENT_NAME_PREFIX = '$ai_'

// Capture turns OpenTelemetry MCP server spans into `$mcp_*` events on the ai lane.
export const OTEL_MCP_EVENT_NAME_PREFIX = '$mcp_'

export const AI_LANE_EVENT_NAME_PREFIXES = [AI_EVENT_NAME_PREFIX, OTEL_MCP_EVENT_NAME_PREFIX]

export const AI_EVENT_BYTES_PROPERTY = '$ai_event_bytes'

export function isAiEventName(event: string): boolean {
    return event.startsWith(AI_EVENT_NAME_PREFIX)
}

export function isAiLaneEventName(event: string): boolean {
    return AI_LANE_EVENT_NAME_PREFIXES.some((prefix) => event.startsWith(prefix))
}

// Anything that writes a cost onto an event must gate on this set. A cost on any
// other event type is never priced or labeled by processCost, and the AI
// observability usage report sums $ai_total_cost_usd across every AI event type,
// so a cost on a span is counted a second time.
export const COSTED_AI_EVENT_TYPES = new Set(['$ai_generation', '$ai_embedding', '$ai_evaluation'])
