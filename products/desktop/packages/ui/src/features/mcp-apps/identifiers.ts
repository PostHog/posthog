import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import type { ComponentType } from "react";

export type McpAppHostComponent = ComponentType<
  ToolViewProps & {
    mcpToolName: string;
    serverName: string;
    toolName: string;
  }
>;

export const MCP_APP_HOST_COMPONENT = Symbol.for(
  "posthog.ui.McpAppHostComponent",
);

// The sandbox proxy iframe `src` — the one host-specific seam of McpAppHost.
// Electron supplies an isolated-origin custom-protocol URL ("mcp-sandbox://proxy");
// web supplies a blob/separate-origin URL of the same proxy HTML.
export type McpSandboxProxyUrlProvider = () => string;

export const MCP_SANDBOX_PROXY_URL = Symbol.for(
  "posthog.ui.McpSandboxProxyUrl",
);
