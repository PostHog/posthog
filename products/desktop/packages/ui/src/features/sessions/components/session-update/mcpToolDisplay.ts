import { getPostHogExecDisplay } from "@posthog/core/sessions/posthogExecDisplay";
import {
  formatPiMcpToolName,
  readMcpProxyCallDetails,
  readMcpToolDescriptor,
  readPiMcpCallDetails,
} from "@posthog/shared";
import type { ToolCall } from "@posthog/ui/features/sessions/types";

export function mcpToolDisplayName(toolCall: ToolCall): string | undefined {
  const details =
    readPiMcpCallDetails(toolCall.details) ??
    readMcpProxyCallDetails(toolCall._meta);
  if (details?.kind === "search") {
    return `Searching MCP tools for "${details.query}"`;
  }
  if (details?.kind === "tool") {
    const posthogDisplay = getPostHogExecDisplay({
      tool: details.name,
      args: details.args,
    });
    const descriptor = readMcpToolDescriptor(toolCall._meta);
    const label = posthogDisplay?.label ?? descriptor?.title;
    return label
      ? formatPiMcpToolName(details.name, label)
      : formatPiMcpToolName(details.name);
  }

  const descriptor = readMcpToolDescriptor(toolCall._meta);
  if (descriptor) {
    return formatPiMcpToolName(
      `mcp__${descriptor.server}__${descriptor.tool}`,
      descriptor.title,
    );
  }

  if (toolCall.title.startsWith("mcp_")) {
    return formatPiMcpToolName(toolCall.title);
  }

  return toolCall.title === "mcp" ? "MCP" : undefined;
}
