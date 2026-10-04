import {
  ClaudeIntegrationUnavailableError,
  type UserClaudeIntegration,
} from "@posthog/api-client/posthog-client";
import { useServiceOptional } from "@posthog/di/react";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
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

export function claudeCloudAccountQueryKey(
  authIdentity: string | null,
): readonly ["claude-cloud-account", string] {
  return ["claude-cloud-account", authIdentity ?? "anonymous"] as const;
}

export interface ClaudeCloudConnectResult {
  integration: UserClaudeIntegration | null;
  localSaveError: Error | null;
}

export function useClaudeCloudAccount(options?: {
  enabled?: boolean;
}): UseQueryResult<UserClaudeIntegration | null> {
  const client = useOptionalAuthenticatedClient();
  const authIdentity = useAuthStateValue(getAuthIdentity);
  return useQuery({
    queryKey: claudeCloudAccountQueryKey(authIdentity),
    queryFn: () => {
      if (!client) throw new Error("Log in to PostHog first.");
      return client.getClaudeUserIntegration();
    },
    enabled: !!client && (options?.enabled ?? true),
    retry: false,
    meta: AUTH_SCOPED_QUERY_META,
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
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (token) => {
      if (!client) throw new Error("Log in to PostHog first.");
      let integration: UserClaudeIntegration | null = null;
      try {
        integration = await client.connectClaudeUserIntegration(token);
      } catch (error) {
        if (
          !(error instanceof ClaudeIntegrationUnavailableError) ||
          !tokenStore
        )
          throw error;
      }
      if (!integration) {
        await tokenStore?.save(token);
        return { integration: null, localSaveError: null };
      }
      let localSaveError: Error | null = null;
      if (tokenStore) {
        try {
          await tokenStore.save(token);
        } catch (error) {
          localSaveError =
            error instanceof Error ? error : new Error(String(error));
        }
      }
      return { integration, localSaveError };
    },
    onSuccess: ({ integration, localSaveError }) => {
      queryClient.setQueryData(
        claudeCloudAccountQueryKey(authIdentity),
        integration,
      );
      if (!localSaveError) {
        queryClient.setQueryData(claudeSubscriptionTokenQueryKey, true);
      }
    },
  });
}

export function useDisconnectClaudeCloudAccount(
  tokenStore: ClaudeSubscriptionTokenSettings | null,
): UseMutationResult<void, Error, void> {
  const client = useOptionalAuthenticatedClient();
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      if (!client) throw new Error("Log in to PostHog first.");
      await client.disconnectClaudeUserIntegration();
      await tokenStore?.clear();
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: claudeCloudAccountQueryKey(authIdentity),
      });
      void queryClient.invalidateQueries({
        queryKey: claudeSubscriptionTokenQueryKey,
      });
    },
  });
}
