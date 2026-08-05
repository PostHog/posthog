import type { McpToolPermissionRequest } from "@posthog/shared";
import { mcpToolKey, posthogToolMeta } from "@posthog/shared";
import type { PermissionToolCall } from "@posthog/ui/features/permissions/types";

export function buildPiMcpPermissionToolCall(
  request: McpToolPermissionRequest,
): PermissionToolCall {
  const mcp = { server: request.serverName, tool: request.toolName };

  return {
    toolCallId: request.requestId,
    title: `The agent wants to call ${request.toolName} (${request.serverName})`,
    kind: "other",
    content: request.description
      ? [
          {
            type: "content",
            content: { type: "text", text: request.description },
          },
        ]
      : [],
    rawInput: request.arguments,
    _meta: posthogToolMeta({
      toolName: mcpToolKey(mcp),
      mcp,
      mcpInstallationId: request.installationId,
    }),
  };
}
