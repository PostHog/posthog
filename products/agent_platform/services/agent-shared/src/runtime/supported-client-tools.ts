/**
 * The `kind:'client'` tool ids the connecting client declared it can actually
 * execute this session. The client sends them in the /run BODY
 * (`supported_client_tools`, see `ChatRunBodySchema`); the ingress stashes them
 * on `trigger_metadata.supported_client_tools`; the runner reads them here.
 *
 * The runner uses this to decide, for an interactive client tool (one that
 * punches out a UI — e.g. `connect_mcp`, `set_secret`), whether THIS client can
 * render the form, or whether it must fall back to a relayed URL on a client
 * that can't (Slack / MCP, or any client that didn't declare the tool). A UX
 * hint, never a security boundary.
 *
 * Distinct from `client_kind` (a coarse "which client app" tag): this is the
 * per-tool capability list.
 */
export function readSessionSupportedClientTools(triggerMetadata: Record<string, unknown> | null | undefined): string[] {
    if (!triggerMetadata) {
        return []
    }
    const raw = triggerMetadata.supported_client_tools
    return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === 'string' && v.length > 0) : []
}
