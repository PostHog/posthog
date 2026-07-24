import type { McpServerStatus, Query } from "@anthropic-ai/claude-agent-sdk";
import { Logger } from "../../../utils/logger";

export type McpToolApprovalState = "approved" | "needs_approval" | "do_not_use";

/** Maps MCP tool keys (e.g. `mcp__server__tool`) to their backend approval state. */
export type McpToolApprovals = Record<string, McpToolApprovalState>;

export interface McpToolMetadata {
  readOnly: boolean;
  name: string;
  description?: string;
  approvalState?: McpToolApprovalState;
}

const mcpToolMetadataCache: Map<string, McpToolMetadata> = new Map();

const PENDING_RETRY_INTERVAL_MS = 1_000;
const PENDING_MAX_RETRIES = 10;

export function sanitizeMcpServerName(name: string): string {
  return name.replace(/[^a-zA-Z0-9_-]/g, "_");
}

function buildToolKey(serverName: string, toolName: string): string {
  return `mcp__${serverName}__${toolName}`;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function fetchMcpToolMetadata(
  q: Query,
  logger: Logger = new Logger({ debug: false, prefix: "[McpToolMetadata]" }),
): Promise<void> {
  let retries = 0;

  while (retries <= PENDING_MAX_RETRIES) {
    let statuses: McpServerStatus[];
    try {
      statuses = await q.mcpServerStatus();
    } catch (error) {
      logger.error("Failed to fetch MCP server status", {
        error: error instanceof Error ? error.message : String(error),
      });
      return;
    }

    const pendingServers = statuses.filter((s) => s.status === "pending");

    for (const server of statuses) {
      if (server.status !== "connected" || !server.tools) {
        continue;
      }

      let readOnlyCount = 0;
      for (const tool of server.tools) {
        const toolKey = buildToolKey(server.name, tool.name);
        const readOnly = tool.annotations?.readOnly === true;

        const existing = mcpToolMetadataCache.get(toolKey);
        mcpToolMetadataCache.set(toolKey, {
          readOnly,
          name: tool.name,
          description: tool.description,
          approvalState: existing?.approvalState,
        });
        if (readOnly) readOnlyCount++;
      }

      logger.info("Fetched MCP tool metadata", {
        serverName: server.name,
        toolCount: server.tools.length,
        readOnlyCount,
      });
    }

    if (pendingServers.length === 0) {
      return;
    }

    retries++;
    if (retries > PENDING_MAX_RETRIES) {
      logger.warn("Gave up waiting for pending MCP servers", {
        pendingServers: pendingServers.map((s) => s.name),
      });
      return;
    }

    logger.info("Waiting for pending MCP servers", {
      pendingServers: pendingServers.map((s) => s.name),
      retry: retries,
    });
    await delay(PENDING_RETRY_INTERVAL_MS);
  }
}

export function getMcpToolMetadata(
  toolName: string,
): McpToolMetadata | undefined {
  return mcpToolMetadataCache.get(toolName);
}

export function isMcpToolReadOnly(toolName: string): boolean {
  const metadata = mcpToolMetadataCache.get(toolName);
  return metadata?.readOnly === true;
}

export function getConnectedMcpServerNames(): string[] {
  const names = new Set<string>();
  for (const key of mcpToolMetadataCache.keys()) {
    const parts = key.split("__");
    if (parts.length >= 3) names.add(parts[1]);
  }
  return [...names];
}

/** Snapshot of every tool currently in the metadata cache. Used by the
 *  context-breakdown estimator to size the MCP category. */
export function getCachedMcpTools(): McpToolMetadata[] {
  return [...mcpToolMetadataCache.values()];
}

/**
 * Servers whose tools default to needs_approval when no per-tool state is
 * cached. Seeded with the run's relayed MCP servers: relayed tools execute on
 * the user's machine, so they always ask regardless of permission mode
 * (docs/cloud-mcp-relay.md security posture).
 */
const alwaysAskMcpServers = new Set<string>();

export function setAlwaysAskMcpServers(serverNames: string[]): void {
  alwaysAskMcpServers.clear();
  for (const name of serverNames) alwaysAskMcpServers.add(name);
}

export function getMcpToolApprovalState(
  toolName: string,
): McpToolApprovalState | undefined {
  const explicit = mcpToolMetadataCache.get(toolName)?.approvalState;
  if (explicit) return explicit;
  const server = toolName.split("__")[1];
  if (server && alwaysAskMcpServers.has(server)) return "needs_approval";
  return undefined;
}

export function setMcpToolApprovalStates(approvals: McpToolApprovals): void {
  for (const [toolKey, approvalState] of Object.entries(approvals)) {
    const existing = mcpToolMetadataCache.get(toolKey);
    if (existing) {
      existing.approvalState = approvalState;
    } else {
      mcpToolMetadataCache.set(toolKey, {
        readOnly: false,
        name: toolKey,
        approvalState,
      });
    }
  }
}

export function clearMcpToolMetadataCache(): void {
  mcpToolMetadataCache.clear();
}
