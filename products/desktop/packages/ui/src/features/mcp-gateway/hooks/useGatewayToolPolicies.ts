import type {
  McpApprovalState,
  McpResolvedToolPolicy,
} from "@posthog/api-client/posthog-client";
import {
  isAgentPolicyState,
  isPolicyStateAllowedByCeiling,
} from "@posthog/core/mcp-gateway/gatewayServers";
import {
  autoRefreshRetryDelayMs,
  shouldAutoRefreshTools,
  shouldRetryAutoRefresh,
} from "@posthog/core/mcp-servers/toolRefresh";
import {
  type GatewayPolicyScope,
  gatewayKeys,
} from "@posthog/ui/features/mcp-gateway/hooks/gatewayKeys";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

// Module-scoped on purpose: this must survive remounts so revisiting a server
// whose catalog is genuinely empty doesn't re-list on every visit. Entries are
// dropped on failure so a transient error isn't a permanent dead end. Tests
// that exercise auto-discovery clear it in beforeEach.
const autoDiscovered = new Set<string>();

export function resetGatewayToolAutoDiscovery(): void {
  autoDiscovered.clear();
}

function scopeParams(scope: GatewayPolicyScope) {
  return {
    scope_type: scope.scopeType,
    scope_user_id: scope.scopeUserId,
    scope_service_account_id: scope.scopeServiceAccountId,
  };
}

/** Tool catalog of one gateway server, resolved for one policy scope. */
export function useGatewayToolPolicies(
  serverId: string,
  scope: GatewayPolicyScope,
  options: {
    enabled?: boolean;
    /**
     * The caller's own installation. When set, an empty catalog lists tools
     * from the upstream server once — the backstop for connections made
     * before this existed, or whose connect-time listing failed.
     */
    autoDiscoverWith?: string | null;
  } = {},
) {
  const queryClient = useQueryClient();
  const queryKey = gatewayKeys.tools(serverId, scope);

  const { data: policies, isLoading } = useAuthenticatedQuery(
    queryKey,
    (client) => client.getMcpGatewayToolPolicies(serverId, scopeParams(scope)),
    { enabled: options.enabled ?? true },
  );

  // The upsert responds with the re-resolved catalog, so write it straight
  // into the current scope's cache. Other scopes can inherit from this one,
  // so mark them stale without immediately refetching the just-updated scope
  // and racing the mutation response with an eventually consistent read.
  const applyResult = useCallback(
    (result: McpResolvedToolPolicy[]) => {
      queryClient.invalidateQueries({
        queryKey: gatewayKeys.serverTools(serverId),
        refetchType: "none",
      });
      queryClient.setQueryData(queryKey, result);
    },
    [queryClient, queryKey, serverId],
  );

  const setPolicyMutation = useAuthenticatedMutation(
    (client, vars: { toolName: string; state: McpApprovalState }) => {
      if (scope.scopeType === "agent" && !isAgentPolicyState(vars.state)) {
        return Promise.reject(
          new Error("Agents cannot use approval-gated tool policies"),
        );
      }
      return client.upsertMcpGatewayToolPolicies(serverId, {
        ...scopeParams(scope),
        policies: [{ tool_name: vars.toolName, policy_state: vars.state }],
      });
    },
    {
      onSuccess: applyResult,
      onError: (error: Error) =>
        toast.error(error.message || "Failed to update tool policy"),
    },
  );

  const setAllMutation = useAuthenticatedMutation(
    (
      client,
      vars: { state: McpApprovalState; toolNames?: readonly string[] },
    ) => {
      if (scope.scopeType === "agent" && !isAgentPolicyState(vars.state)) {
        return Promise.reject(
          new Error("Agents cannot use approval-gated tool policies"),
        );
      }
      const targetNames = vars.toolNames ? new Set(vars.toolNames) : null;
      const editable = (policies ?? []).filter(
        (policy) =>
          !policy.locked &&
          (scope.scopeType === "team" ||
            isPolicyStateAllowedByCeiling(vars.state, policy.team_state)) &&
          (!targetNames || targetNames.has(policy.tool_name)),
      );
      return client.upsertMcpGatewayToolPolicies(serverId, {
        ...scopeParams(scope),
        policies: editable.map((policy) => ({
          tool_name: policy.tool_name,
          policy_state: vars.state,
        })),
      });
    },
    {
      onSuccess: applyResult,
      onError: (error: Error) =>
        toast.error(error.message || "Failed to update tool policies"),
    },
  );

  // Re-lists tools from the upstream server via the caller's installation.
  const silentRefreshRef = useRef(false);
  const attemptedThisMount = useRef(new Set<string>());
  const refreshMutation = useAuthenticatedMutation(
    (client, installationId: string) =>
      client.refreshMcpInstallationTools(installationId),
    {
      // A silent listing retries a few times with backoff before it gives up;
      // a manual refresh reports its first failure.
      retry: (failureCount) =>
        shouldRetryAutoRefresh(failureCount, silentRefreshRef.current),
      retryDelay: autoRefreshRetryDelayMs,
      onSuccess: () => {
        silentRefreshRef.current = false;
        queryClient.invalidateQueries({
          queryKey: gatewayKeys.serverTools(serverId),
        });
        queryClient.invalidateQueries({ queryKey: gatewayKeys.servers });
      },
      onError: (error: Error, installationId) => {
        // Auto-discovery is background work: no toast, but drop the marker so
        // the next mount tries again instead of leaving the page empty forever.
        if (silentRefreshRef.current) {
          silentRefreshRef.current = false;
          autoDiscovered.delete(installationId);
          return;
        }
        toast.error(error.message || "Failed to refresh tools");
      },
    },
  );

  const autoDiscoverWith = options.autoDiscoverWith ?? null;
  const policyCount = (policies ?? []).length;
  // Undefined means the catalog query hasn't resolved (or is disabled) — an
  // empty array is what proves there is nothing to show.
  const catalogResolved = policies !== undefined;
  const refreshIsPending = refreshMutation.isPending;
  const refreshMutate = refreshMutation.mutate;

  useEffect(() => {
    if (!autoDiscoverWith || !catalogResolved) return;
    const fire = shouldAutoRefreshTools({
      autoRefreshIfEmpty: true,
      installationId: autoDiscoverWith,
      isLoading,
      toolsLength: policyCount,
      // The module-level marker is dropped when a listing fails so a later
      // mount retries; the per-mount one is not, because this effect re-runs
      // when the failed mutation settles and would otherwise fire again at
      // once, looping against the upstream server until it rate-limits.
      alreadyRefreshed:
        autoDiscovered.has(autoDiscoverWith) ||
        attemptedThisMount.current.has(autoDiscoverWith),
      refreshPending: refreshIsPending,
    });
    if (!fire) return;
    autoDiscovered.add(autoDiscoverWith);
    attemptedThisMount.current.add(autoDiscoverWith);
    silentRefreshRef.current = true;
    refreshMutate(autoDiscoverWith);
  }, [
    autoDiscoverWith,
    catalogResolved,
    isLoading,
    policyCount,
    refreshIsPending,
    refreshMutate,
  ]);

  return {
    policies: policies ?? [],
    policiesLoading: isLoading,
    setPolicy: setPolicyMutation.mutate,
    setAll: (state: McpApprovalState, toolNames?: readonly string[]) =>
      setAllMutation.mutate({ state, toolNames }),
    setAllPending: setAllMutation.isPending,
    refresh: refreshMutation.mutate,
    refreshPending: refreshMutation.isPending,
  };
}
