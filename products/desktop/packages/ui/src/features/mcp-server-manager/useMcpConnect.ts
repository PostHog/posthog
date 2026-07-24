import type {
  McpAuthType,
  McpServerInstallation,
} from "@posthog/api-client/posthog-client";
import {
  type IOAuthCallback,
  installCustomWithOAuth,
  reauthorizeWithOAuth,
} from "@posthog/core/mcp-servers/installFlow";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { toast } from "@posthog/ui/primitives/toast";
import { useQueryClient } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useMemo } from "react";

export const mcpKeys = {
  servers: ["mcp", "servers"] as const,
  installations: ["mcp", "installations"] as const,
  icon: (domain: string, theme: "light" | "dark") =>
    ["mcp", "icon", domain, theme] as const,
  tools: (installationId: string) =>
    ["mcp", "installations", installationId, "tools"] as const,
};

type HostTRPCClient = ReturnType<typeof useHostTRPCClient>;

/** Host OAuth callback over the desktop's `mcpCallback` tRPC (deep link / dev
 *  HTTP). The one seam the install flow needs from the host. */
export function createOAuthCallback(
  trpcClient: HostTRPCClient,
): IOAuthCallback {
  return {
    getCallbackUrl: () => trpcClient.mcpCallback.getCallbackUrl.query(),
    openAndWaitForCallback: (args) =>
      trpcClient.mcpCallback.openAndWaitForCallback.mutate(args),
  };
}

export interface CustomServerInput {
  name: string;
  url: string;
  description: string;
  auth_type: McpAuthType;
  api_key?: string;
  client_id?: string;
  client_secret?: string;
}

/**
 * Shared MCP connect/list primitives: the `mcp_store` install flow behind an
 * injectable host OAuth callback, plus the team's installations query. Consumed
 * by both the standalone MCP-servers scene and the agent-applications builder.
 */
export function useMcpConnect() {
  const trpc = useHostTRPC();
  const trpcClient = useHostTRPCClient();
  const oauth = useMemo(() => createOAuthCallback(trpcClient), [trpcClient]);
  const queryClient = useQueryClient();

  const installationsQuery = useAuthenticatedQuery(
    mcpKeys.installations,
    (client) => client.getMcpServerInstallations(),
  );

  const invalidateInstallations = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: mcpKeys.installations });
  }, [queryClient]);

  const connectCustomMutation = useAuthenticatedMutation(
    (client, vars: CustomServerInput) =>
      installCustomWithOAuth(client, oauth, vars),
    {
      onSuccess: (data) => {
        if (data && "success" in data && data.success) {
          toast.success("Server added");
        } else if (data && "error" in data && data.error) {
          toast.error(data.error);
        }
        invalidateInstallations();
      },
      onError: (error: Error) =>
        toast.error(error.message || "Failed to add server"),
    },
  );

  const reauthorizeMutation = useAuthenticatedMutation(
    (client, installationId: string) =>
      reauthorizeWithOAuth(client, oauth, installationId),
    {
      onSuccess: (data) => {
        if (data && "success" in data && data.success) {
          toast.success("Server reconnected");
        } else if (data && "error" in data && data.error) {
          toast.error(data.error);
        }
        invalidateInstallations();
      },
      onError: (error: Error) =>
        toast.error(error.message || "Failed to reconnect server"),
    },
  );

  useSubscription(
    trpc.mcpCallback.onOAuthComplete.subscriptionOptions(undefined, {
      onData: (data) => {
        if (data.status === "success") {
          invalidateInstallations();
        }
      },
    }),
  );

  // Awaitable refetch so a caller that just connected can read the freshly
  // created installation back (it's keyed `(team, user, url)` server-side).
  const refetchInstallations = useCallback(async () => {
    const res = await installationsQuery.refetch();
    return (res.data ?? []) as McpServerInstallation[];
  }, [installationsQuery]);

  return {
    oauth,
    installations: installationsQuery.data as
      | McpServerInstallation[]
      | undefined,
    installationsLoading: installationsQuery.isLoading,
    invalidateInstallations,
    refetchInstallations,
    connectCustom: connectCustomMutation.mutate,
    // Awaitable variant — resolves when the OAuth callback completes (or
    // immediately for an api-key install). Used by the builder's connect_mcp
    // punch-out, which must attach the resulting connection to a spec.
    connectCustomAsync: connectCustomMutation.mutateAsync,
    connectCustomPending: connectCustomMutation.isPending,
    reauthorize: reauthorizeMutation.mutate,
    reauthorizePending: reauthorizeMutation.isPending,
  };
}
