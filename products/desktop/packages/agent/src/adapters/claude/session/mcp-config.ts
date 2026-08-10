import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { NewSessionRequest } from "@agentclientprotocol/sdk";
import type { McpServerConfig } from "@anthropic-ai/claude-agent-sdk";
import type {
  LocalMcpServerDescriptor,
  LocalMcpServerScope,
  LocalMcpTransport,
} from "@posthog/shared";
import type { Logger } from "../../../utils/logger";

export interface ClaudeJsonMcpServerEntry {
  name: string;
  scope: LocalMcpServerScope;
  config: McpServerConfig;
}

/**
 * Reads the user's MCP servers from ~/.claude.json: the top-level `mcpServers`
 * section plus, when `cwd` is given, the `projects[cwd].mcpServers` section. A
 * project-scoped server replaces a user-scoped one with the same name,
 * matching how Claude Code merges the two sections.
 */
export function loadUserClaudeJsonMcpServerEntries(
  cwd?: string,
  logger?: Logger,
  homeDir: string = os.homedir(),
): ClaudeJsonMcpServerEntry[] {
  const claudeJsonPath = path.join(homeDir, ".claude.json");

  let raw: string;
  try {
    raw = fs.readFileSync(claudeJsonPath, "utf8");
  } catch {
    return [];
  }

  let cfg: {
    mcpServers?: unknown;
    projects?: Record<string, { mcpServers?: unknown }>;
  };
  try {
    cfg = JSON.parse(raw);
  } catch (err) {
    logger?.warn("Failed to parse ~/.claude.json", {
      error: err instanceof Error ? err.message : String(err),
    });
    return [];
  }

  const sections: Array<{ scope: LocalMcpServerScope; servers: unknown }> = [
    { scope: "user", servers: cfg.mcpServers },
    {
      scope: "project",
      servers: cwd ? cfg.projects?.[cwd]?.mcpServers : undefined,
    },
  ];

  const byName = new Map<string, ClaudeJsonMcpServerEntry>();
  for (const { scope, servers } of sections) {
    if (!servers || typeof servers !== "object") continue;
    for (const [name, config] of Object.entries(
      servers as Record<string, McpServerConfig>,
    )) {
      byName.set(name, { name, scope, config });
    }
  }
  return [...byName.values()];
}

export function loadUserClaudeJsonMcpServers(
  cwd: string,
  logger?: Logger,
  homeDir: string = os.homedir(),
): Record<string, McpServerConfig> {
  const servers: Record<string, McpServerConfig> = {};
  for (const entry of loadUserClaudeJsonMcpServerEntries(
    cwd,
    logger,
    homeDir,
  )) {
    servers[entry.name] = entry.config;
  }
  return servers;
}

export function sanitizeHeaders(
  headers: unknown,
): Record<string, string> | undefined {
  if (!headers || typeof headers !== "object") return undefined;
  const entries = Object.entries(headers as Record<string, unknown>).filter(
    (entry): entry is [string, string] => typeof entry[1] === "string",
  );
  return entries.length > 0 ? Object.fromEntries(entries) : undefined;
}

/**
 * A raw ~/.claude.json entry parsed into a normalized transport, including the
 * stdio `env` that the relay executor needs to spawn the process (the
 * host-agnostic {@link LocalMcpTransport} deliberately drops it as secrets).
 * Both the descriptor normalizer ({@link toTransport}) and the relay's SDK
 * transport builder read entries through here, so they can't drift on how a
 * legacy bare-`url` or type-less entry is interpreted.
 */
export type ParsedClaudeJsonTransport =
  | { kind: "http" | "sse"; url: string; headers?: Record<string, string> }
  | {
      kind: "stdio";
      command: string;
      args?: string[];
      env?: Record<string, string>;
    }
  | { kind: "unknown" };

export function parseClaudeJsonTransport(
  config: McpServerConfig,
): ParsedClaudeJsonTransport {
  // ~/.claude.json is hand-editable, so treat the parsed config as untyped.
  const raw = config as Record<string, unknown>;
  const type = typeof raw.type === "string" ? raw.type : undefined;
  const url = typeof raw.url === "string" ? raw.url : undefined;
  const command = typeof raw.command === "string" ? raw.command : undefined;

  if ((type === "http" || type === "sse") && url) {
    return { kind: type, url, headers: sanitizeHeaders(raw.headers) };
  }
  if ((type === undefined || type === "stdio") && command) {
    const args = Array.isArray(raw.args)
      ? raw.args.filter((arg): arg is string => typeof arg === "string")
      : undefined;
    return { kind: "stdio", command, args, env: sanitizeHeaders(raw.env) };
  }
  // Legacy entries can carry a bare `url` with no `type`; streamable HTTP is
  // the current default transport, so read them as http.
  if (type === undefined && url) {
    return { kind: "http", url, headers: sanitizeHeaders(raw.headers) };
  }
  return { kind: "unknown" };
}

function toTransport(config: McpServerConfig): LocalMcpTransport {
  const transport = parseClaudeJsonTransport(config);
  switch (transport.kind) {
    case "http":
    case "sse":
      return {
        type: transport.kind,
        url: transport.url,
        headers: transport.headers,
      };
    case "stdio":
      // Drop `env` — the descriptor shape excludes stdio secrets.
      return {
        type: "stdio",
        command: transport.command,
        args: transport.args,
      };
    default:
      return { type: "unknown" };
  }
}

/**
 * The user's ~/.claude.json MCP servers as host-agnostic descriptors
 * (`@posthog/shared`), with the raw config normalized per transport and stdio
 * `env` values dropped — they routinely hold secrets consumers of the
 * descriptor shape have no use for.
 */
export function loadUserClaudeJsonMcpServerDescriptors(
  cwd?: string,
  logger?: Logger,
  homeDir: string = os.homedir(),
): LocalMcpServerDescriptor[] {
  return loadUserClaudeJsonMcpServerEntries(cwd, logger, homeDir).map(
    (entry) => ({
      name: entry.name,
      scope: entry.scope,
      transport: toTransport(entry.config),
    }),
  );
}

export function parseMcpServers(
  params: Pick<NewSessionRequest, "mcpServers">,
  logger?: Logger,
): Record<string, McpServerConfig> {
  const mcpServers: Record<string, McpServerConfig> = {};
  if (!Array.isArray(params.mcpServers)) {
    return mcpServers;
  }

  for (const server of params.mcpServers) {
    if ("type" in server) {
      if (server.type === "http" || server.type === "sse") {
        mcpServers[server.name] = {
          type: server.type,
          url: server.url,
          headers: server.headers
            ? Object.fromEntries(
                server.headers.map((e: { name: string; value: string }) => [
                  e.name,
                  e.value,
                ]),
              )
            : undefined,
        };
      } else {
        // ACP 0.22 introduced the `sdk` McpServerConfig variant; the SDK
        // adapter doesn't construct in-process servers, so surface a warning
        // rather than silently dropping the entry.
        logger?.warn("parseMcpServers: dropping unsupported MCP server type", {
          name: server.name,
          type: (server as { type: string }).type,
        });
      }
    } else {
      mcpServers[server.name] = {
        type: "stdio",
        command: server.command,
        args: server.args,
        env: server.env
          ? Object.fromEntries(server.env.map((e) => [e.name, e.value]))
          : undefined,
      };
    }
  }

  return mcpServers;
}
