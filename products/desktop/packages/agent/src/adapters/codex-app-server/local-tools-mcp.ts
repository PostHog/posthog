/**
 * Builds the stdio local-tools MCP server config to inject into a Codex
 * app-server thread's `config.mcp_servers`.
 * Returns the ACP `McpServerStdio` shape so the existing translation layer stays
 * the single owner of the ACP→Codex map.
 */

import type { McpServerStdio } from "@agentclientprotocol/sdk";
import { ghTokenEnv } from "@posthog/git/signed-commit";
import { resolveGithubToken } from "../../utils/github-token";
import { resolveBundledMcpScript } from "../../utils/resolve-bundled-script";
import {
  enabledLocalTools,
  LOCAL_TOOLS_MCP_NAME,
  type LocalToolCtx,
  type LocalToolGateMeta,
} from "../local-tools";
import { resolveTaskId } from "../session-meta";

/**
 * Gate inputs the local-tools server needs beyond `LocalToolGateMeta`: the task id
 * and the base branch the signed-git tools default to. Self-contained so this
 * module doesn't depend on the hub agent's session-meta type.
 */
export interface LocalToolsMeta extends LocalToolGateMeta {
  taskId?: string;
  taskRunId?: string;
  persistence?: { taskId?: string };
  baseBranch?: string;
}

function toMcpServerStdio(
  ctx: LocalToolCtx,
  enabledNames: string[],
): McpServerStdio {
  const scriptPath = resolveBundledMcpScript(
    "adapters/codex-app-server/local-tools-mcp-server.js",
  );
  const ctxBase64 = Buffer.from(JSON.stringify(ctx)).toString("base64");
  const env = [
    { name: "POSTHOG_LOCAL_TOOLS_CTX", value: ctxBase64 },
    { name: "POSTHOG_LOCAL_TOOLS_ENABLED", value: enabledNames.join(",") },
    // Codex spawns this command with ELECTRON_RUN_AS_NODE removed from its own
    // env (spawn.ts). In packaged desktop installs process.execPath is the app
    // binary, which boots the full app without this var. Inert on real node.
    { name: "ELECTRON_RUN_AS_NODE", value: "1" },
  ];
  if (ctx.token) {
    // Token also on the child env so its own git remote ops authenticate.
    env.push(
      ...Object.entries(ghTokenEnv(ctx.token)).map(([name, value]) => ({
        name,
        value,
      })),
    );
  }
  return {
    name: LOCAL_TOOLS_MCP_NAME,
    command: process.execPath,
    args: [scriptPath],
    env,
  };
}

/**
 * Returns the local-tools stdio server config to inject, or null when no tool's
 * gate passes (e.g. local/desktop run with no GH token). Tools self-gate via the
 * registry; the server is only injected when at least one passes.
 */
export function buildLocalToolsServer(
  ctx: { cwd?: string },
  meta: LocalToolsMeta | undefined,
): McpServerStdio | null {
  const cwd = ctx.cwd;
  if (!cwd) {
    return null;
  }
  const toolCtx: LocalToolCtx = {
    cwd,
    token: resolveGithubToken(),
    taskId: resolveTaskId(meta),
    taskRunId: meta?.taskRunId,
    baseBranch: meta?.baseBranch,
  };
  const tools = enabledLocalTools(toolCtx, meta);
  if (tools.length === 0) {
    return null;
  }
  return toMcpServerStdio(
    toolCtx,
    tools.map((t) => t.name),
  );
}
