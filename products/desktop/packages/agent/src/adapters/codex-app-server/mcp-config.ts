import type { McpServer } from "@agentclientprotocol/sdk";
import { isPostHogExecDescriptor } from "../../posthog-exec-permission";
import { sanitizeMcpServerName } from "../claude/mcp/tool-metadata";

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
 * Codex requires `mcp_servers` keys to match `^[a-zA-Z0-9_-]+$` and fails the
 * offending server's startup otherwise (silently: the thread starts, the
 * server's tools just never appear), so display names like "Google Calendar"
 * or "Linear (Jane Doe)" from the MCP Store must be sanitized before keying
 * the map. Reuses the Claude adapter's sanitizer so an installation produces
 * the same `mcp__<server>__<tool>` keys under both adapters. A collision after
 * sanitization gets a numeric suffix, because a plain map write would silently
 * drop one of the colliding servers.
 */
export function codexMcpServerName(name: string): string {
  return sanitizeMcpServerName(name) || "mcp-server";
}

function uniqueCodexMcpServerName(name: string, taken: Set<string>): string {
  const base = codexMcpServerName(name);
  let key = base;
  for (let i = 2; taken.has(key); i++) {
    key = `${base}_${i}`;
  }
  taken.add(key);
  return key;
}

/**
 * Whether a codex-reported server key can belong to the server named `name`.
 * {@link toCodexMcpServers} registers `codexMcpServerName(name)` or, after a
 * collision, that base plus `_<n>`, and the assignment depends on the order
 * and content of the whole server list, which consumers of codex-reported
 * keys (the relay always-ask gate) do not see. Accepting every form the
 * assignment can produce keeps those consumers fail-closed: a false positive
 * (two raw names that share a sanitized base) asks for approval, never
 * skips it.
 */
export function codexKeyMatchesMcpServerName(
  key: string,
  name: string,
): boolean {
  if (key === name) return true;
  const base = codexMcpServerName(name);
  if (key === base) return true;
  return key.startsWith(`${base}_`) && /^\d+$/.test(key.slice(base.length + 1));
}

/**
 * Translates the ACP `McpServer[]` into the shape Codex's app-server expects under
 * `config.mcp_servers` — ACP encodes env/headers as `{ name, value }[]`, Codex
 * wants plain string maps, and keys must satisfy codex's server-name pattern
 * (see {@link codexMcpServerName}). Returns undefined when there's nothing to
 * inject.
 */
export function toCodexMcpServers(
  servers: McpServer[] | undefined,
  options?: { gatePosthogExec?: boolean },
): Record<string, CodexMcpServerConfig> | undefined {
  if (!servers || servers.length === 0) {
    return undefined;
  }

  const out: Record<string, CodexMcpServerConfig> = {};
  const taken = new Set<string>();
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
      out[uniqueCodexMcpServerName(server.name, taken)] = {
        command: server.command,
        args: server.args ?? [],
        ...(env ? { env } : {}),
        ...policy,
      };
    } else if ("url" in server && server.url) {
      const headers = pairsToRecord(server.headers);
      out[uniqueCodexMcpServerName(server.name, taken)] = {
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
