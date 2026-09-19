import type { UserCodexIntegration } from "@posthog/api-client/posthog-client";
import { useHostTRPCClient } from "@posthog/host-router/react";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { connectCodexCloudAccount } from "@posthog/ui/features/settings/connectCodexCloudAccount";
import {
  type UseMutationResult,
  type UseQueryResult,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export const codexCloudAccountQueryKey = ["codex-cloud-account"] as const;

/** The command the user runs before Connect. The CODEX_HOME keeps this login apart from `~/.codex`. */
export const CODEX_CLOUD_LOGIN_COMMAND =
  "CODEX_HOME=~/.codex-posthog codex login --device-auth";

export function useCodexCloudAccount(): UseQueryResult<UserCodexIntegration> {
  const client = useOptionalAuthenticatedClient();
  return useQuery({
    queryKey: codexCloudAccountQueryKey,
    queryFn: () => {
      if (!client) throw new Error("Log in to PostHog first.");
      return client.getCodexUserIntegration();
    },
    enabled: !!client,
    retry: false,
  });
}

export function useConnectCodexCloudAccount(): UseMutationResult<
  UserCodexIntegration,
  Error,
  void
> {
  const client = useOptionalAuthenticatedClient();
  const hostClient = useHostTRPCClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => {
      if (!client) throw new Error("Log in to PostHog first.");
      return connectCodexCloudAccount(client, {
        read: () => hostClient.agent.codexCloudAuthFileRead.query(),
        remove: () => hostClient.agent.codexCloudAuthFileRemove.mutate(),
      });
    },
    onSuccess: (integration) => {
      queryClient.setQueryData(codexCloudAccountQueryKey, integration);
    },
  });
}

export function useDisconnectCodexCloudAccount(): UseMutationResult<
  void,
  Error,
  void
> {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => {
      if (!client) throw new Error("Log in to PostHog first.");
      return client.disconnectCodexUserIntegration();
    },
    onSuccess: () => {
      queryClient.setQueryData<UserCodexIntegration>(
        codexCloudAccountQueryKey,
        {
          status: "not_connected",
          plan_type: null,
          email: null,
          connected_at: null,
        },
      );
    },
  });
}
