import type {
  McpApprovalState,
  McpInstallationTool,
} from "@posthog/api-client/posthog-client";
import { isPolicyStateAllowedByCeiling } from "@posthog/core/mcp-gateway/gatewayServers";
import { dispatchBulkApproval } from "@posthog/core/mcp-servers/toolBulk";
import {
  autoRefreshRetryDelayMs,
  shouldAutoRefreshTools,
  shouldRetryAutoRefresh,
} from "@posthog/core/mcp-servers/toolRefresh";
import { useHostTRPC } from "@posthog/host-router/react";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect, useRef } from "react";
import { mcpKeys } from "./useMcpServers";

interface UseMcpInstallationToolsOptions {
  includeRemoved?: boolean;
  autoRefreshIfEmpty?: boolean;
  teamScope?: boolean;
}

// Module-scoped on purpose: state must survive remounts of this hook so a
// detail-page revisit doesn't re-fire the auto-refresh. Tests that exercise
// auto-refresh need to clear this in beforeEach.
const autoRefreshedInstallations = new Set<string>();

export function useMcpInstallationTools(
  installationId: string | null,
  options: UseMcpInstallationToolsOptions = {},
) {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  const queryKey = [
    ...mcpKeys.tools(installationId ?? ""),
    { includeRemoved: !!options.includeRemoved },
  ] as const;

  const { data: tools, isLoading } = useAuthenticatedQuery(
    queryKey,
    (client) =>
      installationId
        ? client.getMcpInstallationTools(installationId, {
            includeRemoved: options.includeRemoved,
          })
        : Promise.resolve([] as McpInstallationTool[]),
    {
      enabled: !!installationId,
      refetchOnMount: "always",
    },
  );

  const invalidate = useCallback(() => {
    if (!installationId) return;
    queryClient.invalidateQueries({
      queryKey: options.teamScope
        ? mcpKeys.installations
        : mcpKeys.tools(installationId),
    });
  }, [installationId, options.teamScope, queryClient]);

  const setToolApprovalMutation = useAuthenticatedMutation(
    (client, vars: { toolName: string; approval_state: McpApprovalState }) => {
      if (!installationId) {
        return Promise.reject(new Error("No installation selected"));
      }
      return client.updateMcpToolApproval(
        installationId,
        vars.toolName,
        vars.approval_state,
      );
    },
    {
      onSuccess: () => {
        invalidate();
      },
      onError: (error: Error) => {
        toast.error(error.message || "Failed to update tool approval");
      },
    },
  );

  const setBulkApprovalMutation = useAuthenticatedMutation(
    (
      client,
      vars: {
        approval_state: McpApprovalState;
        targetTools?: McpInstallationTool[];
      },
    ) => {
      if (!installationId) {
        return Promise.reject(new Error("No installation selected"));
      }
      const eligibleTools = (vars.targetTools ?? tools ?? []).filter(
        (tool) =>
          !tool.locked &&
          (options.teamScope ||
            isPolicyStateAllowedByCeiling(
              vars.approval_state,
              tool.team_state,
            )),
      );
      return dispatchBulkApproval(
        client,
        installationId,
        eligibleTools,
        vars.approval_state,
      );
    },
    {
      onSuccess: () => {
        invalidate();
      },
      onError: (error: Error) => {
        toast.error(error.message || "Failed to update tool approvals");
      },
    },
  );

  const silentRefreshRef = useRef(false);
  const attemptedThisMount = useRef(new Set<string>());

  const refreshMutation = useAuthenticatedMutation(
    (client) => {
      if (!installationId) {
        return Promise.reject(new Error("No installation selected"));
      }
      return client.refreshMcpInstallationTools(installationId);
    },
    {
      // A silent listing retries a few times with backoff before it gives up;
      // a manual refresh reports its first failure.
      retry: (failureCount) =>
        shouldRetryAutoRefresh(failureCount, silentRefreshRef.current),
      retryDelay: autoRefreshRetryDelayMs,
      onSuccess: () => {
        const silent = silentRefreshRef.current;
        silentRefreshRef.current = false;
        if (!silent) toast.success("Tools refreshed");
        invalidate();
        queryClient.invalidateQueries({ queryKey: mcpKeys.installations });
      },
      onError: (error: Error) => {
        const silent = silentRefreshRef.current;
        silentRefreshRef.current = false;
        if (!silent) {
          toast.error(error.message || "Failed to refresh tools");
          return;
        }
        // A silent refresh reports nothing, so leaving the id marked would
        // strand the page empty for the session. Let the next mount retry.
        if (installationId) autoRefreshedInstallations.delete(installationId);
      },
    },
  );

  const toolsLength = (tools ?? []).length;
  const refreshIsPending = refreshMutation.isPending;
  const refreshMutate = refreshMutation.mutate;

  useEffect(() => {
    if (!installationId) return;
    const fire = shouldAutoRefreshTools({
      autoRefreshIfEmpty: !!options.autoRefreshIfEmpty,
      installationId,
      isLoading,
      toolsLength,
      // The module-level marker is dropped when a listing fails so a later
      // mount retries; the per-mount one is not, because this effect re-runs
      // when the failed mutation settles and would otherwise fire again at
      // once, looping against the upstream server until it rate-limits.
      alreadyRefreshed:
        autoRefreshedInstallations.has(installationId) ||
        attemptedThisMount.current.has(installationId),
      refreshPending: refreshIsPending,
    });
    if (!fire) return;
    autoRefreshedInstallations.add(installationId);
    attemptedThisMount.current.add(installationId);
    silentRefreshRef.current = true;
    refreshMutate(undefined);
  }, [
    options.autoRefreshIfEmpty,
    installationId,
    isLoading,
    toolsLength,
    refreshIsPending,
    refreshMutate,
  ]);

  useSubscription(
    trpc.mcpCallback.onOAuthComplete.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data.status === "success") {
          invalidate();
        }
      },
    }),
  );

  return {
    tools: tools ?? [],
    isLoading,
    setToolApproval: setToolApprovalMutation.mutate,
    setBulkApproval: (
      approval_state: McpApprovalState,
      targetTools?: McpInstallationTool[],
    ) => setBulkApprovalMutation.mutate({ approval_state, targetTools }),
    bulkPending: setBulkApprovalMutation.isPending,
    refresh: () => refreshMutation.mutate(undefined),
    refreshPending: refreshMutation.isPending,
  };
}
