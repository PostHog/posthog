import { loadUserClaudeJsonMcpServerDescriptors } from "@posthog/agent/adapters/claude/session/mcp-config";
import type {
  McpAuthType,
  McpServerInstallation,
} from "@posthog/api-client/types";
import { classifyLocalMcpServer } from "@posthog/core/local-mcp/localMcpImport";
import type { LocalMcpServerDescriptor } from "@posthog/shared";
import type { Sheet, SheetItem } from "./sheet";

interface OAuthRedirect {
  redirect_url: string;
}

// The account's MCP servers, as PostHog holds them.
export interface McpClient {
  installations(): Promise<McpServerInstallation[]>;
  install(options: {
    name: string;
    url: string;
    auth_type: McpAuthType;
    api_key?: string;
    install_source: "posthog-code";
  }): Promise<McpServerInstallation | OAuthRedirect>;
  // The link that signs an installed server in again.
  authorize(installationId: string): Promise<OAuthRedirect>;
}

// How a custom server signs the account in. None is an API-key server without a key, as PostHog holds one.
export type McpAuth = "none" | "api_key" | "oauth";

export const MCP_AUTHS: { id: McpAuth; label: string; detail: string }[] = [
  { id: "none", label: "No sign-in", detail: "the server is open" },
  { id: "api_key", label: "API key", detail: "pasted next" },
  { id: "oauth", label: "Sign in with the browser", detail: "OAuth" },
];

export interface McpPoll {
  every: number;
  timeout: number;
}

// An OAuth sign-in finishes in the browser and lands on PostHog, so the TUI asks until the installation is no longer pending.
const SIGN_IN_POLL: McpPoll = { every: 2_000, timeout: 180_000 };

async function untilSignedIn(
  client: McpClient,
  done: (installation: McpServerInstallation) => boolean,
  { every, timeout }: McpPoll,
): Promise<McpServerInstallation> {
  const until = Date.now() + timeout;
  for (;;) {
    const found = (await client.installations()).find(done);
    if (found) return found;
    if (Date.now() >= until)
      throw new Error("The sign-in did not finish in time");
    await new Promise((resolve) => setTimeout(resolve, every));
  }
}

const sameName = (a: string, b: string): boolean =>
  a.localeCompare(b, undefined, { sensitivity: "base" }) === 0;

// Adds a custom server to the account. A server that signs in with the browser is installed pending, and comes
// back once PostHog has finished its sign-in.
export async function addMcpServer(
  client: McpClient,
  {
    name,
    url,
    auth,
    apiKey,
  }: { name: string; url: string; auth: McpAuth; apiKey?: string },
  open: (url: string) => void,
  poll: McpPoll = SIGN_IN_POLL,
): Promise<McpServerInstallation> {
  const result = await client.install({
    name,
    url,
    auth_type: auth === "oauth" ? "oauth" : "api_key",
    ...(auth === "api_key" && apiKey && { api_key: apiKey }),
    install_source: "posthog-code",
  });
  if (!("redirect_url" in result)) return result;
  open(result.redirect_url);
  return untilSignedIn(
    client,
    (installation) =>
      (sameName(installation.name, name) ||
        sameName(installation.display_name ?? "", name)) &&
      !installation.pending_oauth,
    poll,
  );
}

export async function reauthorizeMcpServer(
  client: McpClient,
  installation: McpServerInstallation,
  open: (url: string) => void,
  poll: McpPoll = SIGN_IN_POLL,
): Promise<McpServerInstallation> {
  const { redirect_url } = await client.authorize(installation.id);
  open(redirect_url);
  return untilSignedIn(
    client,
    (candidate) =>
      candidate.id === installation.id &&
      !candidate.needs_reauth &&
      !candidate.pending_oauth,
    poll,
  );
}

// One typed answer on a sheet, for the add-a-server questions.
export function mcpTextSheet(
  title: string,
  description: string,
  placeholder: string,
): Sheet {
  return {
    title,
    description,
    items: [{ label: "Answer", input: { placeholder, text: "" } }],
    footer: "Enter to send · Esc to cancel",
  };
}

export function mcpAuthSheet(): Sheet {
  return {
    title: "How does it sign you in?",
    items: MCP_AUTHS.map(({ label, detail }) => ({ label, detail })),
    footer: "Enter to select · Esc to cancel",
  };
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
    ? "needs signing in again · Enter to sign in"
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

export const ADD_LABEL = "Add a server";

export interface McpSheet extends Sheet {
  // The items that do something: the servers Enter signs in again, the add row, and the relay switch.
  reauth: Map<number, McpServerInstallation>;
  addServer: number;
  relayToggle: number;
}

// /mcp: the account's servers first, then the ones on this machine, then the switch that relays those to cloud chats.
export function mcpSheet(
  installations: McpServerInstallation[],
  locals: LocalMcpServerDescriptor[],
  { relay = false }: { relay?: boolean } = {},
): McpSheet {
  const relayed = new Set(relay ? relayedMcpServers(locals) : []);
  const account = installations
    .map((installation) => ({
      installation,
      label: installation.display_name || installation.name,
      detail: `PostHog · ${installationState(installation)}`,
    }))
    .sort(byLabel);
  const reauth = new Map(
    account.flatMap(({ installation }, index) =>
      installation.needs_reauth ? [[index, installation] as const] : [],
    ),
  );
  const items: SheetItem[] = [
    ...account.map(({ label, detail }) => ({ label, detail })),
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
  return {
    title: "MCP servers",
    description:
      "PostHog's servers reach every chat. This machine's come from ~/.claude.json; the TUI must stay open while a cloud chat uses one.",
    items: [
      ...items,
      { label: ADD_LABEL, detail: "a URL, and how it signs you in" },
      { label: RELAY_LABEL, current: relay },
    ],
    reauth,
    addServer: items.length,
    relayToggle: items.length + 1,
    footer: "Enter to choose · Esc to close",
  };
}
