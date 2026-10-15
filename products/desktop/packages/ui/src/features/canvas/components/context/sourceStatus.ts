import type { ContextSourceStatus } from "@posthog/core/canvas/contextSources";
import type { ContextSourceState } from "@posthog/ui/features/canvas/hooks/useContextSources";

const CONNECT_VERB: Partial<Record<ContextSourceStatus, string>> = {
  needs_reauth: "Reconnect",
  pending_oauth: "Finish authorizing",
};

export function connectLabel(
  state: ContextSourceState,
  withName = false,
): string {
  if (state.connecting) return "Waiting";
  if (state.needsCredentials) return "Open MCP servers";
  const verb = CONNECT_VERB[state.status] ?? "Connect";
  return withName ? `${verb} ${state.source.name}` : verb;
}

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
