import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import type { ComponentType } from "react";

export type McpToolBlockComponent = ComponentType<
  ToolViewProps & { mcpToolName: string }
>;

export const MCP_TOOL_BLOCK_COMPONENT = Symbol.for(
  "posthog.ui.McpToolBlockComponent",
);
