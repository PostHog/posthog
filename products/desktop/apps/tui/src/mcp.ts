import { loadUserClaudeJsonMcpServerDescriptors } from "@posthog/agent/adapters/claude/session/mcp-config";
import type { McpServerInstallation } from "@posthog/api-client/types";
import { classifyLocalMcpServer } from "@posthog/core/local-mcp/localMcpImport";
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

// The local servers a sandbox cannot reach on its own: a process on this machine, or a private address. A cloud
// chat gets them through the TUI, which answers the sandbox's calls against the real server, as the desktop app does.
export const relayedMcpServers = (
  locals: LocalMcpServerDescriptor[],
): string[] =>
  locals
    .map(classifyLocalMcpServer)
    .filter((server) => server.availability === "requires_desktop")
    .map((server) => server.name)
    .sort();

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

export const RELAY_LABEL = "Cloud chats reach this machine's servers";

export interface McpSheet extends Sheet {
  // The index of the relay switch, the one item that does something.
  relayToggle: number;
}

// /mcp: the account's servers first, then the ones on this machine, then the switch that relays those to cloud chats.
export function mcpSheet(
  installations: McpServerInstallation[],
  locals: LocalMcpServerDescriptor[],
  { relay = false }: { relay?: boolean } = {},
): McpSheet {
  const relayed = new Set(relay ? relayedMcpServers(locals) : []);
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
        detail: [
          "this machine",
          transportOf(server),
          ...(relayed.has(server.name) ? ["relayed to cloud chats"] : []),
        ].join(" · "),
      }))
      .sort(byLabel),
  ];
  if (items.length === 0)
    items.push({
      label: "No MCP servers yet",
      disabled: "add one in PostHog's MCP settings",
    });
  return {
    title: "MCP servers",
    description:
      "PostHog's servers reach every chat. This machine's come from ~/.claude.json; the TUI must stay open while a cloud chat uses one.",
    items: [...items, { label: RELAY_LABEL, current: relay }],
    relayToggle: items.length,
    footer: "Enter to switch · Esc to close",
  };
}
