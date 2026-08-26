// Types for the team MCP gateway API (`/api/projects/{id}/mcp_gateway/*`).
// Hand-written mirrors of the Django serializers in
// products/mcp_store/backend/presentation/gateway_views.py — these endpoints
// ship behind the `mcp-gateway` flag and are not in the generated OpenAPI
// client yet.
import type { Schemas } from "./generated";
import type { McpApprovalState, McpAuthType, McpCategory } from "./types";

export type McpGatewayUser = Schemas.UserBasic;

export type McpGatewayScopeType = "team" | "member" | "agent";
/**
 * How far an agent grant reaches: "personal" backs only the sharer's own
 * runs, "team" backs every run of the agent in the project.
 */
export type McpAgentGrantScope = "personal" | "team";
export type McpServiceAccountStatus = "active" | "paused";
export type McpAuditDecision = "auto" | "approved" | "pending" | "blocked";
export type McpAuditQuickFilter = "all" | "agents" | "approvals" | "blocked";
export type McpPolicyDecidedBy =
  | "rule"
  | "scope"
  | "team"
  | "preset"
  | "legacy"
  | "default";

/** One member's connection to a gateway server. */
export interface McpGatewayConnection {
  installation_id: string;
  user: McpGatewayUser;
  last_used_at: string | null;
  pending_oauth: boolean;
  needs_reauth: boolean;
}

/** The requesting user's own connection to a gateway server. */
export interface McpGatewayYourConnection {
  installation_id: string;
  /** Per-connection switch — false when self-disabled. */
  is_enabled: boolean;
  pending_oauth: boolean;
  needs_reauth: boolean;
  last_used_at: string | null;
}

/**
 * One agent's access to a gateway server, on behalf of one member. A server
 * can carry several rows for the same agent when multiple members share it.
 */
export interface McpGatewayAgentAccess {
  service_account_id: string;
  /** The member whose connection the agent uses. */
  user: McpGatewayUser;
  scope: McpAgentGrantScope;
  name: string;
  /** Agent identity handle, e.g. posthog-support. */
  handle: string;
  status: McpServiceAccountStatus;
  last_active_at: string | null;
  granted_by: McpGatewayUser | null;
}

/** A server registered in the team's gateway, with connection summary. */
export interface McpGatewayServer {
  id: string;
  name: string;
  url: string;
  description: string;
  category: McpCategory;
  is_team_enabled: boolean;
  icon_key: string;
  docs_url: string;
  template_id: string | null;
  /**
   * Fixed authentication type for catalog templates. Null for custom
   * servers, where each member chooses when connecting.
   */
  template_auth_type: McpAuthType | null;
  tool_count: number;
  /** Members with a connection to this server. Admin-only; empty for members. */
  connections: McpGatewayConnection[];
  your_connection: McpGatewayYourConnection | null;
  agents: McpGatewayAgentAccess[];
  /** Ids of members whose access an admin has turned off. */
  revoked_user_ids: number[];
  is_revoked_for_you: boolean;
  created_by: McpGatewayUser | null;
  created_at: string;
  updated_at: string;
}

export interface McpGatewayServerUpdate {
  name?: string;
  description?: string;
  category?: McpCategory;
  /** Master switch — off means members and agents can neither see nor call the server. */
  is_team_enabled?: boolean;
}

/** Which policy scope a tools query or policy upsert targets. */
export interface McpGatewayPolicyScope {
  scope_type?: McpGatewayScopeType;
  /** Member scope target. Defaults to the requesting user. */
  scope_user_id?: number;
  /** Agent scope target. Required when scope_type is "agent". */
  scope_service_account_id?: string;
}

export interface McpToolPolicyEntry {
  tool_name: string;
  policy_state: McpApprovalState;
}

/** One tool with its effective policy for the requested scope. */
export interface McpResolvedToolPolicy {
  tool_name: string;
  description: string;
  input_schema: unknown;
  policy_state: McpApprovalState;
  /** What the team-level chain yields, ignoring the scope. Null when the team imposes nothing. */
  team_state: McpApprovalState | null;
  /** True when a rule or Blocked team ceiling leaves no editable state. */
  locked: boolean;
  decided_by: McpPolicyDecidedBy;
  /** Matching org rule name, when decided_by is "rule". */
  rule_name: string;
  rule_description: string;
}

export interface McpServiceAccount {
  id: string;
  name: string;
  description: string;
  /** Stable identity handle the agent authenticates as, e.g. posthog-support. */
  handle: string;
  status: McpServiceAccountStatus;
  /** Masked bearer token; the full token is only shown once. */
  token_mask: string;
  server_ids: string[];
  last_active_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface McpServiceAccountWithToken extends McpServiceAccount {
  /** The full bearer token. Returned exactly once — on creation. */
  token: string;
}

export interface McpAuditActorServiceAccount {
  id: string;
  name: string;
  handle: string;
}

export interface McpAuditEvent {
  id: string;
  created_at: string;
  server_name: string;
  tool_name: string;
  decision: McpAuditDecision;
  actor_user: McpGatewayUser | null;
  actor_service_account: McpAuditActorServiceAccount | null;
  /** Denormalized actor label (email or handle) that survives deletion. */
  actor_label: string;
  /**
   * Member whose connection an agent call used. Null for member calls and
   * for owners whose account has since been deleted.
   */
  credential_owner: McpGatewayUser | null;
  /** Scope of the agent grant the call used. Empty for member calls. */
  grant_scope: McpAgentGrantScope | "";
}

export interface McpAuditCounts {
  all: number;
  agents: number;
  approvals: number;
  blocked: number;
}

export interface McpAuditPage {
  count: number;
  results: McpAuditEvent[];
}

export interface TeamMcpGatewayConfig {
  allow_custom_servers: boolean;
  /** Whether members may share MCP connections with agents and manage agent tool policies. */
  allow_member_agent_access: boolean;
  /**
   * Whether catalog servers the team never touched (no gateway row) are
   * enabled. Covers templates published after the admin last curated.
   */
  default_servers_enabled: boolean;
  /** Whether the requesting user can administer the gateway. */
  is_admin: boolean;
}

export interface TeamMcpGatewayConfigUpdate {
  allow_custom_servers?: boolean;
  allow_member_agent_access?: boolean;
  default_servers_enabled?: boolean;
}

/** One team member's gateway posture (admin overview). */
export interface McpGatewayMemberSummary {
  user: McpGatewayUser;
  is_org_admin: boolean;
  /** Gateway servers the member has a personal connection to. */
  connected_server_ids: string[];
  /** Gateway servers an admin turned off for this member. */
  revoked_server_ids: string[];
}

/**
 * Gateway options accepted by install_custom / install_template. Credentials
 * are always personal to the installer; agents reach them through grants.
 */
export interface McpGatewayInstallSharingOptions {
  /** Whether the server starts enabled for the whole team. */
  team_enabled?: boolean;
  /** Service accounts to grant the server to at install time, when team settings allow it. */
  agent_ids?: string[];
}
