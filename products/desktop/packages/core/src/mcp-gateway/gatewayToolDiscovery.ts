import type { McpGatewayServer } from "@posthog/api-client/posthog-client";
import { normalizeGatewayServerUrl } from "./gatewayServers";

/**
 * A gateway server's tool catalog only exists once something lists it from the
 * upstream server through a caller's credential. Connecting stores the
 * credential but discovers nothing, so without this the registry keeps a row
 * with zero tools until an admin hits the manual refresh button.
 */
export interface GatewayToolDiscoveryClient {
  getMcpGatewayServers(): Promise<McpGatewayServer[]>;
  refreshMcpInstallationTools(installationId: string): Promise<unknown>;
}

/** How to find the just-connected server in the re-read registry. */
export interface GatewayServerMatch {
  serverId?: string | null;
  /** The caller's own installation, for flows that only know the credential. */
  installationId?: string | null;
  templateId?: string | null;
  url?: string | null;
}

export type GatewayToolDiscoverySkip =
  | "no-server"
  | "no-connection"
  | "already-populated";

export interface GatewayToolDiscoveryResult {
  serverId: string | null;
  installationId: string | null;
  discovered: boolean;
  skipped?: GatewayToolDiscoverySkip;
}

/**
 * Match a registry row by id, then installation, then template, then URL. The
 * add-server flow only knows the URL it submitted; connect-from-catalog only
 * knows the template id; reconnect only knows the installation.
 */
export function findGatewayServer(
  servers: McpGatewayServer[],
  match: GatewayServerMatch,
): McpGatewayServer | null {
  if (match.serverId) {
    return servers.find((server) => server.id === match.serverId) ?? null;
  }
  if (match.installationId) {
    const byInstallation = servers.find(
      (server) =>
        server.your_connection?.installation_id === match.installationId,
    );
    if (byInstallation) return byInstallation;
  }
  if (match.templateId) {
    const byTemplate = servers.find(
      (server) => server.template_id === match.templateId,
    );
    if (byTemplate) return byTemplate;
  }
  if (match.url) {
    const target = normalizeGatewayServerUrl(match.url);
    return (
      servers.find(
        (server) => normalizeGatewayServerUrl(server.url) === target,
      ) ?? null
    );
  }
  return null;
}

/**
 * The caller's own installation, when it can actually reach the server.
 * A self-disabled connection still holds a usable credential; one that is
 * mid-OAuth or needs reauth does not.
 */
export function usableInstallationId(
  server: McpGatewayServer | null,
): string | null {
  const connection = server?.your_connection;
  if (!connection) return null;
  if (connection.pending_oauth || connection.needs_reauth) return null;
  return connection.installation_id;
}

/**
 * Discover only when the team has no catalog yet. A populated `tool_count`
 * means someone already listed the tools, and re-listing on every connect
 * would hit the upstream server for nothing.
 */
export function shouldDiscoverGatewayTools(
  server: McpGatewayServer | null,
): boolean {
  if (!server) return false;
  if (server.tool_count > 0) return false;
  return usableInstallationId(server) !== null;
}

/**
 * Re-read the registry after a connect and, if the server still has no tools,
 * list them through the caller's fresh credential. Callers invalidate the
 * returned `serverId`'s tool queries when `discovered` is true.
 */
export async function discoverGatewayTools(
  client: GatewayToolDiscoveryClient,
  match: GatewayServerMatch,
  options: { servers?: McpGatewayServer[] } = {},
): Promise<GatewayToolDiscoveryResult> {
  const servers = options.servers ?? (await client.getMcpGatewayServers());
  const server = findGatewayServer(servers, match);
  if (!server) {
    return {
      serverId: null,
      installationId: null,
      discovered: false,
      skipped: "no-server",
    };
  }
  const installationId = usableInstallationId(server);
  if (!installationId) {
    return {
      serverId: server.id,
      installationId: null,
      discovered: false,
      skipped: "no-connection",
    };
  }
  if (server.tool_count > 0) {
    return {
      serverId: server.id,
      installationId,
      discovered: false,
      skipped: "already-populated",
    };
  }
  await client.refreshMcpInstallationTools(installationId);
  return { serverId: server.id, installationId, discovered: true };
}
