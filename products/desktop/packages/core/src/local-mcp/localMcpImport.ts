import type {
  Adapter,
  CloudMcpServerImport,
  CloudMcpServerRelayDesignation,
  LocalMcpServerDescriptor,
} from "@posthog/shared";
import { isPrivateIpv4Octets, isPrivateIpv6Literal } from "@posthog/shared";
import { inject, injectable } from "inversify";
import { LOCAL_MCP_WORKSPACE_CLIENT } from "./identifiers";

/** The slice of workspace-server this service needs, bound by the host. */
export interface LocalMcpWorkspaceClient {
  listLocalMcpServers(cwd?: string): Promise<LocalMcpServerDescriptor[]>;
}

export type LocalMcpCloudAvailability =
  /** url-based server on a publicly reachable host; can be forwarded to the sandbox. */
  | "importable"
  /** stdio server or private-network URL; only usable through a desktop relay. */
  | "requires_desktop"
  /** the sandbox already provides a server under this name; importing would be rejected. */
  | "built_in"
  /** shape we can't run anywhere (unparseable URL, unrecognized transport). */
  | "unsupported";

export type LocalMcpCloudReason =
  | "public_url"
  | "private_url"
  | "stdio_transport"
  | "reserved_name"
  | "invalid_url"
  | "unsupported_transport";

/**
 * Names the cloud sandbox always provides itself. The run-creation API
 * rejects imports under these names (case-insensitively), so they must never
 * enter the payload — the built-in server covers them.
 */
const RESERVED_CLOUD_MCP_NAMES = new Set(["posthog"]);

export interface LocalMcpCloudClassification {
  name: string;
  availability: LocalMcpCloudAvailability;
  reason: LocalMcpCloudReason;
  /** Sandbox-shaped config; present only when availability is "importable". */
  remote?: CloudMcpServerImport;
}

function parseIpv4(host: string): [number, number, number, number] | null {
  const match = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!match) return null;
  const octets = match.slice(1).map(Number);
  if (octets.some((octet) => octet > 255)) return null;
  return octets as [number, number, number, number];
}

const PRIVATE_HOST_SUFFIXES = [
  ".local",
  ".localhost",
  ".internal",
  ".lan",
  ".home",
  ".home.arpa",
  ".ts.net", // Tailscale MagicDNS
];

/**
 * Heuristic: is this hostname only reachable from the user's own machine or
 * network? Errs toward private — a public server misclassified as private
 * just stays desktop-only, while the reverse would ship an unreachable server
 * to the sandbox.
 */
export function isPrivateHostname(hostname: string): boolean {
  let host = hostname.toLowerCase().replace(/\.$/, "");
  if (host.startsWith("[") && host.endsWith("]")) host = host.slice(1, -1);
  if (host === "" || host === "localhost") return true;

  // IPv6 literal: the shared kernel covers loopback/unspecified, link-local,
  // unique-local, and IPv4-mapped (incl. the hex-group form URL normalizes to).
  if (host.includes(":")) return isPrivateIpv6Literal(host);

  const octets = parseIpv4(host);
  if (octets) return isPrivateIpv4Octets(octets[0], octets[1]);

  // Bare intranet names ("nas", "router") only resolve on the local network.
  if (!host.includes(".")) return true;

  return PRIVATE_HOST_SUFFIXES.some((suffix) => host.endsWith(suffix));
}

function parseHttpUrl(raw: string): URL | null {
  try {
    const url = new URL(raw);
    return url.protocol === "http:" || url.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

export function classifyLocalMcpServer(
  server: LocalMcpServerDescriptor,
): LocalMcpCloudClassification {
  const { name } = server;
  const transport = server.transport;

  if (RESERVED_CLOUD_MCP_NAMES.has(name.toLowerCase())) {
    return { name, availability: "built_in", reason: "reserved_name" };
  }
  if (transport.type === "stdio") {
    return {
      name,
      availability: "requires_desktop",
      reason: "stdio_transport",
    };
  }
  if (transport.type === "unknown") {
    return {
      name,
      availability: "unsupported",
      reason: "unsupported_transport",
    };
  }

  const url = parseHttpUrl(transport.url);
  if (!url) {
    return { name, availability: "unsupported", reason: "invalid_url" };
  }
  if (isPrivateHostname(url.hostname)) {
    return { name, availability: "requires_desktop", reason: "private_url" };
  }
  return {
    name,
    availability: "importable",
    reason: "public_url",
    remote: {
      type: transport.type,
      name,
      url: transport.url,
      headers: Object.entries(transport.headers ?? {}).map(
        ([headerName, value]) => ({ name: headerName, value }),
      ),
    },
  };
}

/** Mirrors the run-creation API's per-field caps (MAX_RELAYED_MCP_SERVERS). */
const MAX_RELAYED_MCP_SERVERS = 20;

export interface LocalMcpServersForRun {
  imported: CloudMcpServerImport[];
  relayed: CloudMcpServerRelayDesignation[];
}

/**
 * Split classified local servers into the run-creation payload's imported and
 * relayed lists for the run's adapter.
 *
 * Claude tolerates an unreachable configured server, so importable (public
 * URL) servers go straight into the sandbox config. Codex hard-fails the whole
 * session on any unreachable MCP server, so for codex runs importable servers
 * ride the relay instead: the loopback relay endpoint always answers codex's
 * reachability probe, and the desktop executes the server from local config —
 * public URLs included. Desktop-only servers relay for every adapter.
 */
export function partitionLocalMcpServersForRun(
  servers: LocalMcpCloudClassification[],
  adapter: Adapter | undefined,
): LocalMcpServersForRun {
  const relayImportable = adapter === "codex";
  const imported = relayImportable
    ? []
    : servers.flatMap((server) => (server.remote ? [server.remote] : []));
  const relayed = servers
    .filter(
      (server) =>
        server.availability === "requires_desktop" ||
        (relayImportable && server.availability === "importable"),
    )
    // Desktop-only servers first: unlike importables they have no other
    // transport, so they must survive the count cap.
    .sort((a, b) =>
      a.availability === b.availability
        ? 0
        : a.availability === "requires_desktop"
          ? -1
          : 1,
    )
    .slice(0, MAX_RELAYED_MCP_SERVERS)
    .map((server) => ({ name: server.name }));
  return { imported, relayed };
}

@injectable()
export class LocalMcpImportService {
  constructor(
    @inject(LOCAL_MCP_WORKSPACE_CLIENT)
    private readonly workspace: LocalMcpWorkspaceClient,
  ) {}

  /**
   * Classifies the user's local MCP servers by whether they can be imported
   * into a cloud sandbox. `cwd` picks up ~/.claude.json project-scoped
   * servers for that checkout in addition to user-scoped ones.
   */
  async getCloudAvailability(
    cwd?: string,
  ): Promise<LocalMcpCloudClassification[]> {
    const servers = await this.workspace.listLocalMcpServers(cwd);
    return servers.map(classifyLocalMcpServer);
  }
}
