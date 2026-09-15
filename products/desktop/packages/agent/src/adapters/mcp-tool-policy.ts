import type { RequestPermissionResponse } from "@agentclientprotocol/sdk";

export const BACKGROUND_MCP_APPROVAL_DENIAL =
  "This tool requires user approval, which is unavailable in background runs. Run this task interactively to approve it.";
export const BLOCKED_MCP_TOOL_DENIAL =
  "This tool has been blocked. To re-enable it, go to Settings > MCP Servers in PostHog.";
export const UNRESOLVED_MCP_TOOL_DENIAL =
  "This tool could not be matched to its approval policy. Refresh the task's MCP configuration before trying again.";

export function permissionDenialReason(
  response: RequestPermissionResponse,
): string | undefined {
  const message = response._meta?.message;
  return response.outcome.outcome === "cancelled" &&
    typeof message === "string" &&
    message.trim()
    ? message
    : undefined;
}
