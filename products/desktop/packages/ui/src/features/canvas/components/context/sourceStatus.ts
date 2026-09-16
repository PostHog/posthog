import type { ContextSourceState } from "@posthog/ui/features/canvas/hooks/useContextSources";

export function connectLabel(state: ContextSourceState): string {
  if (state.needsCredentials) return "Open MCP servers";
  if (state.status === "needs_reauth") return "Reconnect";
  if (state.status === "pending_oauth") return "Finish authorizing";
  return "Connect";
}

/** Why a link from this source is not readable yet, in the status's own words. */
export function unconnectedWarning(state: ContextSourceState): string {
  const name = state.source.name;
  if (state.needsCredentials) {
    return `${name} is not connected. It needs an API key, so it connects from the MCP servers page.`;
  }
  if (state.status === "needs_reauth") {
    return `${name} needs to be authorized again before agents can read this.`;
  }
  if (state.status === "pending_oauth") {
    return `Authorization for ${name} was not finished, so agents cannot read this yet.`;
  }
  return `${name} is not connected, so agents cannot read this yet.`;
}
