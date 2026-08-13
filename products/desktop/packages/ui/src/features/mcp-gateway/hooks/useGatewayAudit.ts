import type { McpAuditQuickFilter } from "@posthog/api-client/posthog-client";
import { gatewayKeys } from "@posthog/ui/features/mcp-gateway/hooks/gatewayKeys";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { keepPreviousData } from "@tanstack/react-query";

export const AUDIT_PAGE_SIZE = 10;

/** One page of the gateway audit log plus the quick-filter counts. */
export function useGatewayAudit(options: {
  quickFilter: McpAuditQuickFilter;
  actorServiceAccountId?: string;
  page: number;
  enabled?: boolean;
}) {
  const { data: pageData, isLoading } = useAuthenticatedQuery(
    gatewayKeys.audit(options),
    (client) =>
      client.getMcpGatewayAuditEvents({
        quickFilter: options.quickFilter,
        actorServiceAccountId: options.actorServiceAccountId,
        limit: AUDIT_PAGE_SIZE,
        offset: options.page * AUDIT_PAGE_SIZE,
      }),
    { enabled: options.enabled ?? true, placeholderData: keepPreviousData },
  );

  const { data: counts } = useAuthenticatedQuery(
    gatewayKeys.auditCounts,
    (client) => client.getMcpGatewayAuditCounts(),
    { enabled: options.enabled ?? true },
  );

  return {
    events: pageData?.results ?? [],
    totalCount: pageData?.count ?? 0,
    auditLoading: isLoading,
    counts: counts ?? null,
  };
}

/** Recent calls for one agent (service-account detail's history table). */
export function useAgentRecentCalls(accountId: string) {
  const { data, isLoading } = useAuthenticatedQuery(
    gatewayKeys.audit({
      quickFilter: "all",
      actorServiceAccountId: accountId,
    }),
    (client) =>
      client.getMcpGatewayAuditEvents({
        actorServiceAccountId: accountId,
        limit: 50,
      }),
  );
  return { events: data?.results ?? [], eventsLoading: isLoading };
}
