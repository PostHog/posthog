import type { McpServer } from "@agentclientprotocol/sdk";
import { isPostHogExecDescriptor } from "../../posthog-exec-permission";

interface CodexMcpServerToolConfig {
  approval_mode: "prompt";
}

interface CodexMcpServerPolicyConfig {
  tools?: Record<string, CodexMcpServerToolConfig>;
}

/**
 * Codex's per-thread `mcp_servers` config entry (stdio: command/args/env; http:
 * url + headers), accepted under `thread/start`'s `config.mcp_servers`.
 */
export type CodexMcpServerConfig =
  | (CodexMcpServerPolicyConfig & {
      command: string;
      args: string[];
      env?: Record<string, string>;
    })
  | (CodexMcpServerPolicyConfig & {
      url: string;
      http_headers?: Record<string, string>;
    });

/**
 * Translates the ACP `McpServer[]` into the shape Codex's app-server expects under
 * `config.mcp_servers` — ACP encodes env/headers as `{ name, value }[]`, Codex
 * wants plain string maps. Returns undefined when there's nothing to inject.
 */
export function toCodexMcpServers(
  servers: McpServer[] | undefined,
  options?: { gatePosthogExec?: boolean },
): Record<string, CodexMcpServerConfig> | undefined {
  if (!servers || servers.length === 0) {
    return undefined;
  }

  const out: Record<string, CodexMcpServerConfig> = {};
  for (const server of servers) {
    // `approval_mode: "prompt"` makes codex ask before every exec call; the
    // per-sub-tool regex filtering happens in the adapter's approval handlers,
    // which auto-accept calls the session's permission policy does not gate.
    const policy =
      options?.gatePosthogExec &&
      isPostHogExecDescriptor({ server: server.name, tool: "exec" })
        ? { tools: { exec: { approval_mode: "prompt" as const } } }
        : {};
    if ("command" in server && server.command) {
      const env = pairsToRecord(server.env);
      out[server.name] = {
        command: server.command,
        args: server.args ?? [],
        ...(env ? { env } : {}),
        ...policy,
      };
    } else if ("url" in server && server.url) {
      const headers = pairsToRecord(server.headers);
      out[server.name] = {
        url: server.url,
        ...(headers ? { http_headers: headers } : {}),
        ...policy,
      };
    }
  }

  return Object.keys(out).length > 0 ? out : undefined;
}

function pairsToRecord(
  pairs: Array<{ name: string; value: string }> | undefined,
): Record<string, string> | undefined {
  if (!pairs || pairs.length === 0) {
    return undefined;
  }
  const record: Record<string, string> = {};
  for (const { name, value } of pairs) {
    record[name] = value;
  }
  return record;
}
