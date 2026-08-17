import type { McpAuditQuickFilter } from "@posthog/api-client/posthog-client";

/** Scope a tool-policy query resolves against. */
export interface GatewayPolicyScope {
  scopeType: "team" | "member" | "agent";
  /** Member scope target; omitted means the requesting user. */
  scopeUserId?: number;
  scopeServiceAccountId?: string;
  /** Display label for the scope pill ("Team default", "You", agent name…). */
  label: string;
}

export const TEAM_SCOPE: GatewayPolicyScope = {
  scopeType: "team",
  label: "Team default",
};

export const YOU_SCOPE: GatewayPolicyScope = {
  scopeType: "member",
  label: "You",
};

function scopeKey(scope: GatewayPolicyScope): string {
  return [
    scope.scopeType,
    scope.scopeUserId ?? "",
    scope.scopeServiceAccountId ?? "",
  ].join(":");
}

// Keyed under the legacy ["mcp", ...] root so the shell's focus-refresh
// invalidation covers gateway data too.
export const gatewayKeys = {
  all: ["mcp", "gateway"] as const,
  config: ["mcp", "gateway", "config"] as const,
  servers: ["mcp", "gateway", "servers"] as const,
  serverTools: (serverId: string) =>
    ["mcp", "gateway", "servers", serverId, "tools"] as const,
  tools: (serverId: string, scope: GatewayPolicyScope) =>
    ["mcp", "gateway", "servers", serverId, "tools", scopeKey(scope)] as const,
  accounts: ["mcp", "gateway", "accounts"] as const,
  members: ["mcp", "gateway", "members"] as const,
  audit: (options: {
    quickFilter: McpAuditQuickFilter;
    actorServiceAccountId?: string;
    page?: number;
  }) =>
    [
      "mcp",
      "gateway",
      "audit",
      options.quickFilter,
      options.actorServiceAccountId ?? "",
      options.page ?? 0,
    ] as const,
  auditCounts: ["mcp", "gateway", "audit", "counts"] as const,
};
