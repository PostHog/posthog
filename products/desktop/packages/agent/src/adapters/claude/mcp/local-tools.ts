import {
  createSdkMcpServer,
  type McpSdkServerConfigWithInstance,
  tool,
} from "@anthropic-ai/claude-agent-sdk";
import {
  enabledLocalTools,
  LOCAL_TOOLS_MCP_NAME,
  type LocalToolCtx,
  type LocalToolGateMeta,
} from "../../local-tools";

/**
 * In-process SDK MCP server exposing the enabled local tools to the Claude
 * adapter (see `../../local-tools` for the registry). Returns `undefined` when
 * no tool's gate passes, so the caller can skip registering an empty server.
 * Registered per session in `claude-agent.ts`.
 */
export function createLocalToolsMcpServer(
  ctx: LocalToolCtx,
  meta: LocalToolGateMeta | undefined,
): McpSdkServerConfigWithInstance | undefined {
  const tools = enabledLocalTools(ctx, meta);
  if (tools.length === 0) {
    return undefined;
  }
  return createSdkMcpServer({
    name: LOCAL_TOOLS_MCP_NAME,
    version: "1.0.0",
    tools: tools.map((t) =>
      tool(
        t.name,
        t.description,
        t.schema,
        async (args) => t.handler(ctx, args),
        { alwaysLoad: t.alwaysLoad ?? false },
      ),
    ),
  });
}
