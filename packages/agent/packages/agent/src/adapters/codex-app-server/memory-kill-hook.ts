import type { ServerOptions } from "@modelcontextprotocol/sdk/server/index.js";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { tomlBasicString } from "@posthog/agent-contracts";
import { LOCAL_TOOLS_MCP_NAME } from "@posthog/harness/extensions/local-tools";
import { z } from "zod";
import { Logger } from "../../utils/logger";
import {
  createMemoryKillNoticeHook,
  type MemoryKillNoticeHookOptions,
} from "../claude/session/memory-kill-hook";
import type { AppServerRpc } from "./app-server-client";

export const MEMORY_KILL_HOOK_TOOL_NAME = "sandbox_memory_hook";

// Codex starts a subagent's MCP server lazily when it has that server's tool
// catalog cached, and a hook call does not wait for the server to start. A
// subagent that only runs shell commands would then never reach this hook.
// Opting out of the catalog cache makes every thread start the server eagerly.
export const MEMORY_KILL_HOOK_SERVER_OPTIONS: ServerOptions = {
  capabilities: {
    experimental: { "codex/tool-catalog-cache": { cacheable: false } },
  },
};

// Codex serializes sub-agent spawns as `spawn_agent` and only accepts `Agent`
// as a matcher alias, while the shared hook keys on the Claude tool name.
const HOOK_TOOL_NAMES: Record<string, string> = { spawn_agent: "Agent" };

interface ListedMemoryHook {
  key: string;
  currentHash: string;
  source: string;
  eventName: string;
  matcher: string | null;
  handlerType: string;
  server?: string;
  tool?: string;
}

export async function getMemoryKillHookTrust(
  rpc: Pick<AppServerRpc, "request">,
  cwd: string,
): Promise<Record<string, { trusted_hash: string }>> {
  const result = await rpc.request<{
    data: { hooks: ListedMemoryHook[] }[];
  }>("hooks/list", { cwds: [cwd] });
  return Object.fromEntries(
    result.data.flatMap(({ hooks }) =>
      hooks
        .filter(
          (hook) =>
            hook.source === "sessionFlags" &&
            hook.handlerType === "mcpTool" &&
            hook.server === LOCAL_TOOLS_MCP_NAME &&
            hook.tool === MEMORY_KILL_HOOK_TOOL_NAME &&
            hook.matcher === "Bash|Agent" &&
            ["preToolUse", "postToolUse"].includes(hook.eventName),
        )
        .map((hook) => [hook.key, { trusted_hash: hook.currentHash }]),
    ),
  );
}

export function buildMemoryKillHooksConfig(): string {
  const fields = [
    "session_id",
    "cwd",
    "hook_event_name",
    "tool_name",
    "tool_input",
    "tool_use_id",
  ];
  const events = ["PreToolUse", "PostToolUse"].map((event) => {
    const inputFields =
      event === "PostToolUse" ? [...fields, "tool_response"] : fields;
    const input = inputFields
      .map((field) => `${field} = ${tomlBasicString(`\${${field}}`)}`)
      .join(", ");
    return `${event} = [{ matcher = "Bash|Agent", hooks = [{ type = "mcp_tool", server = ${tomlBasicString(LOCAL_TOOLS_MCP_NAME)}, tool = ${tomlBasicString(MEMORY_KILL_HOOK_TOOL_NAME)}, input = { ${input} }, timeout = 10 }] }]`;
  });
  return `hooks={ ${events.join(", ")} }`;
}

export function registerMemoryKillHook(
  server: McpServer,
  options: MemoryKillNoticeHookOptions = {},
): void {
  const hook = createMemoryKillNoticeHook(new Logger({ debug: false }), {
    exitStatusInToolResponse: false,
    ...options,
  });
  server.tool(
    MEMORY_KILL_HOOK_TOOL_NAME,
    "Internal sandbox memory feedback for Codex tool hooks.",
    {
      session_id: z.string(),
      cwd: z.string(),
      hook_event_name: z.enum(["PreToolUse", "PostToolUse"]),
      tool_name: z.string(),
      tool_input: z.record(z.string(), z.unknown()),
      tool_use_id: z.string(),
      tool_response: z.unknown().optional(),
    },
    async (input, extra) => {
      const base = {
        ...input,
        tool_name: HOOK_TOOL_NAMES[input.tool_name] ?? input.tool_name,
        transcript_path: "",
      };
      const result = await hook(
        input.hook_event_name === "PreToolUse"
          ? { ...base, hook_event_name: "PreToolUse" }
          : {
              ...base,
              hook_event_name: "PostToolUse",
              tool_response: input.tool_response,
            },
        input.tool_use_id,
        { signal: extra.signal },
      );
      return { content: [{ type: "text", text: JSON.stringify(result) }] };
    },
  );
}
