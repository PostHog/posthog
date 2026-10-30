import { loadUserClaudeJsonMcpServerDescriptors } from "@posthog/agent/adapters/claude/session/mcp-config";
import type { McpServerInstallation } from "@posthog/api-client/types";
import type { LocalMcpServerDescriptor } from "@posthog/shared";
import type { Sheet, SheetItem } from "./sheet";

// The account's MCP servers, as PostHog holds them.
export interface McpClient {
  installations(): Promise<McpServerInstallation[]>;
}

// The servers in ~/.claude.json, the user's own and the folder's, merged as Claude Code merges them.
export const localMcpServers = (
  cwd: string = process.cwd(),
  homeDir?: string,
): LocalMcpServerDescriptor[] =>
  loadUserClaudeJsonMcpServerDescriptors(cwd, undefined, homeDir);

const installationState = (installation: McpServerInstallation): string =>
  installation.needs_reauth
    ? "needs signing in again"
    : installation.pending_oauth
      ? "finishing sign-in"
      : installation.is_enabled === false
        ? "off"
        : `${installation.tool_count} tools`;

const transportOf = (server: LocalMcpServerDescriptor): string =>
  server.transport.type === "stdio"
    ? [server.transport.command, ...(server.transport.args ?? [])].join(" ")
    : server.transport.type === "unknown"
      ? "unknown transport"
      : server.transport.url;

const byLabel = (a: SheetItem, b: SheetItem): number =>
  a.label.localeCompare(b.label, undefined, { sensitivity: "base" });

// /mcp: the account's servers first, then the ones on this machine.
export function mcpSheet(
  installations: McpServerInstallation[],
  locals: LocalMcpServerDescriptor[],
): Sheet {
  const items: SheetItem[] = [
    ...installations
      .map((installation) => ({
        label: installation.display_name || installation.name,
        detail: `PostHog · ${installationState(installation)}`,
      }))
      .sort(byLabel),
    ...locals
      .map((server) => ({
        label: server.name,
        detail: `this machine · ${transportOf(server)}`,
      }))
      .sort(byLabel),
  ];
  return {
    title: "MCP servers",
    description:
      "PostHog's servers reach every chat. This machine's come from ~/.claude.json.",
    items:
      items.length > 0
        ? items
        : [
            {
              label: "No MCP servers yet",
              disabled: "add one in PostHog's MCP settings",
            },
          ],
    footer: "Esc to close",
  };
}
