/**
 * Absolute deep links into the customer's own PostHog app — the agent's
 * `$ai_*` events are captured into that team's project (see the runner's
 * `RoutingAnalyticsSink`), so the AI observability product is where the rich
 * trace / generation / cost view lives. The console shows lightweight stats
 * inline and links out here for depth.
 *
 * `baseUrl` is the region-aware app URL from `/api/auth/me`
 * (`usePosthogBaseUrl()`); `teamId` from `useSessionTeamId()`. Callers pass
 * `null`-guarded values, so these only run when both are known.
 */

function projectBase(baseUrl: string, teamId: number): string {
    return `${baseUrl.replace(/\/$/, '')}/project/${teamId}`
}

/**
 * One session's trace. `$ai_trace_id` is the session id, so the trace route
 * keys directly on it.
 */
export function aiObservabilityTraceUrl(baseUrl: string, teamId: number, sessionId: string): string {
    return `${projectBase(baseUrl, teamId)}/ai-observability/traces/${encodeURIComponent(sessionId)}`
}

/** The AI-observability traces list — the agent-level "see everything" click-out. */
export function aiObservabilityTracesUrl(baseUrl: string, teamId: number): string {
    return `${projectBase(baseUrl, teamId)}/ai-observability/traces`
}
