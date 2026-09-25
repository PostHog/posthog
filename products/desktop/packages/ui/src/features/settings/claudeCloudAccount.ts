import {
  ClaudeIntegrationUnavailableError,
  type UserClaudeIntegration,
} from "@posthog/api-client/posthog-client";
import { useServiceOptional } from "@posthog/di/react";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS,
  type ClaudeSubscriptionTokenSettings,
  claudeSubscriptionTokenQueryKey,
} from "@posthog/ui/features/settings/claudeSubscriptionTokenSettings";
import {
  type UseMutationResult,
  type UseQueryResult,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

export const claudeCloudAccountQueryKey = ["claude-cloud-account"] as const;

export interface ClaudeCloudConnectResult {
  integration: UserClaudeIntegration | null;
  localClearError: Error | null;
}

export function useClaudeCloudAccount(): UseQueryResult<UserClaudeIntegration | null> {
  const client = useOptionalAuthenticatedClient();
  return useQuery({
    queryKey: claudeCloudAccountQueryKey,
    queryFn: () => {
      if (!client) throw new Error("Log in to PostHog first.");
      return client.getClaudeUserIntegration();
    },
    enabled: !!client,
    retry: false,
  });
}

export function useLocalClaudeToken(): {
  tokenStore: ClaudeSubscriptionTokenSettings | null;
  query: UseQueryResult<boolean>;
} {
  const tokenStore = useServiceOptional<ClaudeSubscriptionTokenSettings>(
    CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS,
  );
  const query = useQuery({
    queryKey: claudeSubscriptionTokenQueryKey,
    queryFn: () => tokenStore?.has() ?? Promise.resolve(false),
    enabled: !!tokenStore,
    retry: false,
  });
  return { tokenStore, query };
}

export function useConnectClaudeCloudAccount(
  tokenStore: ClaudeSubscriptionTokenSettings | null,
): UseMutationResult<ClaudeCloudConnectResult, Error, string> {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (token) => {
      if (!client) throw new Error("Log in to PostHog first.");
      let integration: UserClaudeIntegration;
      try {
        integration = await client.connectClaudeUserIntegration(token);
      } catch (error) {
        if (
          !(error instanceof ClaudeIntegrationUnavailableError) ||
          !tokenStore
        )
          throw error;
        await tokenStore.save(token);
        return { integration: null, localClearError: null };
      }
      let localClearError: Error | null = null;
      if (tokenStore) {
        try {
          await tokenStore.clear();
        } catch (error) {
          localClearError =
            error instanceof Error ? error : new Error(String(error));
        }
      }
      return { integration, localClearError };
    },
    onSuccess: ({ integration, localClearError }) => {
      queryClient.setQueryData(claudeCloudAccountQueryKey, integration);
      if (!integration) {
        queryClient.setQueryData(claudeSubscriptionTokenQueryKey, true);
      } else if (!localClearError) {
        queryClient.setQueryData(claudeSubscriptionTokenQueryKey, false);
      }
    },
  });
}

export function useDisconnectClaudeCloudAccount(
  tokenStore: ClaudeSubscriptionTokenSettings | null,
): UseMutationResult<void, Error, void> {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      if (!client) throw new Error("Log in to PostHog first.");
      await client.disconnectClaudeUserIntegration();
      await tokenStore?.clear();
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: claudeCloudAccountQueryKey,
      });
      void queryClient.invalidateQueries({
        queryKey: claudeSubscriptionTokenQueryKey,
      });
    },
  });
}
