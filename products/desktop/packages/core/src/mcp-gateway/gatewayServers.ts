import type {
  McpApprovalState,
  McpAuditDecision,
  McpGatewayScopeType,
  McpGatewayServer,
  McpGatewayYourConnection,
  McpResolvedToolPolicy,
} from "@posthog/api-client/posthog-client";
import { formatRelativeTimeShort, getLocalDayDiff } from "@posthog/shared";

/** The rail lists the servers the caller has connected, under the rail search. */
export function railConnectedServers(
  servers: McpGatewayServer[],
  search: string,
): McpGatewayServer[] {
  const query = search.trim().toLowerCase();
  return servers.filter(
    (server) =>
      server.your_connection !== null &&
      (!query || server.name.toLowerCase().includes(query)),
  );
}

interface GatewayServerLike {
  name: string;
  description?: string;
  url: string;
  category?: string;
}

function matchesSearchAndCategory(
  entry: GatewayServerLike,
  query: string,
  category: string | null,
): boolean {
  if (category && entry.category !== category) return false;
  if (!query) return true;
  return (
    entry.name.toLowerCase().includes(query) ||
    (entry.description ?? "").toLowerCase().includes(query) ||
    entry.url.toLowerCase().includes(query)
  );
}

/** Home-screen filter: search over name/description/url plus category chip. */
export function filterGatewayServers(
  servers: McpGatewayServer[],
  search: string,
  category: string | null,
): McpGatewayServer[] {
  const query = search.trim().toLowerCase();
  return servers.filter((server) =>
    matchesSearchAndCategory(server, query, category),
  );
}

/** Same search/category filter, for catalog templates on the home screen. */
export function filterCatalogTemplates<T extends GatewayServerLike>(
  templates: T[],
  search: string,
  category: string | null,
): T[] {
  const query = search.trim().toLowerCase();
  return templates.filter((template) =>
    matchesSearchAndCategory(template, query, category),
  );
}

/** Trailing-slash-insensitive URL identity for row/template matching. */
export function normalizeGatewayServerUrl(url: string): string {
  return url.trim().replace(/\/+$/, "");
}

/**
 * The registry is sparse: a catalog template has a gateway row only once
 * someone connected to it or an admin toggled it. "Recommended" templates are
 * the active catalog entries with no row — matched neither by template id nor
 * by URL (trailing-slash-insensitive) — shown as connect-only cards.
 */
export function recommendedCatalogTemplates<
  T extends { id: string; url: string },
>(
  servers: Pick<McpGatewayServer, "template_id" | "url">[],
  templates: T[],
): T[] {
  const rowTemplateIds = new Set<string>();
  const rowUrls = new Set<string>();
  for (const server of servers) {
    if (server.template_id) rowTemplateIds.add(server.template_id);
    rowUrls.add(normalizeGatewayServerUrl(server.url));
  }
  return templates.filter(
    (template) =>
      !rowTemplateIds.has(template.id) &&
      !rowUrls.has(normalizeGatewayServerUrl(template.url)),
  );
}

export function countGatewayServersByCategory(
  servers: McpGatewayServer[],
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const server of servers) {
    counts[server.category] = (counts[server.category] ?? 0) + 1;
  }
  return counts;
}

/**
 * Whether the current user can call this server without connecting first —
 * every credential is the caller's own, so this is their connection's state.
 */
export function isConnectedForYou(server: McpGatewayServer): boolean {
  return (
    !!server.your_connection &&
    getGatewayConnectionStatus(server.your_connection) === "connected"
  );
}

export type GatewayConnectionStatus =
  | "connected"
  | "pending_oauth"
  | "needs_reauth";

/** A persisted installation row is not necessarily a usable connection. */
export function getGatewayConnectionStatus(
  connection: Pick<McpGatewayYourConnection, "pending_oauth" | "needs_reauth">,
): GatewayConnectionStatus {
  if (connection.needs_reauth) return "needs_reauth";
  if (connection.pending_oauth) return "pending_oauth";
  return "connected";
}

export type GatewayRailStatus =
  | GatewayConnectionStatus
  | "team_off"
  | "revoked"
  | "self_disabled";

/**
 * Rail-row status: folds the switches the raw connection status can't see —
 * the admin master switch, per-user revocation, and the caller's own enable
 * toggle — so a connection that can't be used never reads as connected. The
 * auth states only matter once all three switches are on. Null when the
 * caller has no connection.
 */
export function getGatewayRailStatus(
  server: Pick<
    McpGatewayServer,
    "is_team_enabled" | "is_revoked_for_you" | "your_connection"
  >,
): GatewayRailStatus | null {
  const connection = server.your_connection;
  if (!connection) return null;
  if (!server.is_team_enabled) return "team_off";
  if (server.is_revoked_for_you) return "revoked";
  if (!connection.is_enabled) return "self_disabled";
  return getGatewayConnectionStatus(connection);
}

export type GatewayServerRemovalAction =
  | "delete_for_everyone"
  | "delete_for_you"
  | "disconnect";

/**
 * Admins remove custom servers from the team gateway. For members, a custom
 * server they registered themselves is theirs to delete; catalog servers and
 * custom servers registered by somebody else remain team entries, so removing
 * the caller's installation is presented as disconnecting instead.
 *
 * The caller's identity must come in from the session user —
 * `server.connections` is admin-only (empty for members), so it cannot
 * identify a member caller.
 */
export function getGatewayServerRemovalAction(
  server: McpGatewayServer,
  isAdmin: boolean,
  currentUserId: number | null,
): GatewayServerRemovalAction | null {
  if (isAdmin && server.template_id === null) return "delete_for_everyone";

  if (!server.your_connection) return null;

  const personallyAddedCustomServer =
    server.template_id === null &&
    server.created_by !== null &&
    server.created_by.id === currentUserId;

  return personallyAddedCustomServer ? "delete_for_you" : "disconnect";
}

export type GatewayPolicyCounts = Record<McpApprovalState, number>;

export const AGENT_POLICY_STATES = [
  "approved",
  "do_not_use",
] as const satisfies readonly McpApprovalState[];

export type AgentPolicyState = (typeof AGENT_POLICY_STATES)[number];

export function isAgentPolicyState(
  state: McpApprovalState,
): state is AgentPolicyState {
  return state !== "needs_approval";
}

/**
 * Agents have no approval responder. A policy that would wait for approval is
 * therefore unavailable to the agent, just like an explicit block.
 */
export function resolvePolicyStateForScope(
  state: McpApprovalState,
  scopeType: McpGatewayScopeType,
): McpApprovalState {
  return scopeType === "agent" && state === "needs_approval"
    ? "do_not_use"
    : state;
}

const POLICY_STRICTNESS: Record<McpApprovalState, number> = {
  approved: 0,
  needs_approval: 1,
  do_not_use: 2,
};

/** A scope may match the team ceiling or choose a more restrictive state. */
export function isPolicyStateAllowedByCeiling(
  state: McpApprovalState,
  ceiling: McpApprovalState | null | undefined,
): boolean {
  return ceiling === null || ceiling === undefined
    ? true
    : POLICY_STRICTNESS[state] >= POLICY_STRICTNESS[ceiling];
}

export function countPoliciesByState(
  policies: McpResolvedToolPolicy[],
  scopeType: McpGatewayScopeType = "member",
): GatewayPolicyCounts {
  const counts: GatewayPolicyCounts = {
    approved: 0,
    needs_approval: 0,
    do_not_use: 0,
  };
  for (const policy of policies) {
    counts[resolvePolicyStateForScope(policy.policy_state, scopeType)] += 1;
  }
  return counts;
}

/** "2h ago" / "just now" for last-used and last-active timestamps. */
export function formatAgo(timestamp: string | null): string | null {
  if (!timestamp) return null;
  const short = formatRelativeTimeShort(timestamp);
  return short === "now" ? "just now" : `${short} ago`;
}

/** Audit-table timestamp: "Today 09:58", "Yesterday 17:22", "Jul 15 09:12". */
export function formatAuditTime(timestamp: string, now?: Date): string {
  const date = new Date(timestamp);
  const dayDiff = getLocalDayDiff(date, now);
  const time = date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  if (dayDiff <= 0) return `Today ${time}`;
  if (dayDiff === 1) return `Yesterday ${time}`;
  const day = date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  return `${day} ${time}`;
}

export const AUDIT_DECISION_LABELS: Record<McpAuditDecision, string> = {
  auto: "Auto-approved",
  approved: "Approved",
  pending: "Awaiting approval",
  blocked: "Blocked",
};

// Mirrors the backend's destructive-tool heuristic; only used to seed the
// per-tool defaults when sharing a server with an agent.
const DESTRUCTIVE_TOOL_RE =
  /delete|update|post|write|create|run-migration|close|drop|send/;

/** Default policy offered when granting an agent access to a tool. */
export function defaultAgentGrantPolicy(toolName: string): AgentPolicyState {
  return DESTRUCTIVE_TOOL_RE.test(toolName) ? "do_not_use" : "approved";
}
