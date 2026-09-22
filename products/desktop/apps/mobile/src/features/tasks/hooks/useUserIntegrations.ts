import { combineUserGithubRepositories } from "@posthog/core/integrations/repositories";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useAuthStore } from "@/features/auth";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import type { RepositoryOption } from "../types";
import {
  buildUserRepositoryOptions,
  repositoryLoadWarning,
} from "../utils/repositorySelection";

/**
 * User-scoped sibling of {@link useIntegrations}. Reads the authenticated
 * user's personal GitHub integrations (`/api/users/@me/integrations/`) rather
 * than the team-level ones, matching how the desktop app links GitHub per user.
 *
 * Used by the interactive task-creation flow (new task screen, task list empty
 * state, connect prompt).
 *
 * Repos are keyed by the numeric GitHub `installation_id` so the existing
 * number-based picker/`RepositoryOption` keep working; `getUserIntegrationId`
 * maps that back to the `UserIntegration` UUID for task creation. No persisted
 * cache here (unlike the team hook) so it can't clobber the team cache.
 */
export const userIntegrationKeys = {
  all: ["user-integrations"] as const,
  github: () => [...userIntegrationKeys.all, "github"] as const,
  repos: (installationIds: string[]) =>
    [...userIntegrationKeys.all, "repos", installationIds] as const,
};

interface UseUserIntegrationsOptions {
  enabled?: boolean;
}

export function useUserIntegrations(options: UseUserIntegrationsOptions = {}) {
  const { enabled = true } = options;
  const { oauthAccessToken } = useAuthStore();

  const integrationsQuery = useQuery({
    queryKey: userIntegrationKeys.github(),
    queryFn: async () => {
      const integrations =
        await getPostHogApiClient().getGithubUserIntegrations();
      return integrations.map(({ account, ...integration }) => ({
        ...integration,
        account: account
          ? {
              name: account.name ?? undefined,
              type: account.type ?? undefined,
            }
          : undefined,
      }));
    },
    enabled: enabled && !!oauthAccessToken,
  });

  const integrations = enabled ? (integrationsQuery.data ?? []) : [];

  const repositoriesQuery = useQuery({
    queryKey: userIntegrationKeys.repos(
      integrations.map((i) => i.installation_id),
    ),
    queryFn: async () => {
      const results = await Promise.allSettled(
        integrations.map(async (integration) => ({
          installationId: integration.installation_id,
          repositories: (
            await getPostHogApiClient().getGithubUserRepositories(
              integration.installation_id,
            )
          )
            .map((repository) => repository.toLowerCase())
            .filter(Boolean),
        })),
      );

      const combined = combineUserGithubRepositories(
        results.map((result) => ({
          data:
            result.status === "fulfilled"
              ? {
                  userIntegrationId:
                    integrations.find(
                      (integration) =>
                        integration.installation_id ===
                        result.value.installationId,
                    )?.id ?? "",
                  installationId: result.value.installationId,
                  repos: result.value.repositories,
                }
              : undefined,
          isPending: false,
          isError: result.status === "rejected",
          isRefetching: false,
        })),
        integrations.map((integration) => integration.installation_id),
      );

      return {
        byInstallation: combined.reposByInstallationId,
        partialError: repositoryLoadWarning(
          combined.failedInstallationIds.length,
          integrations.length,
        ),
      };
    },
    enabled: enabled && integrations.length > 0,
  });

  const repositoryOptions = useMemo<RepositoryOption[]>(() => {
    return buildUserRepositoryOptions(
      integrations,
      repositoriesQuery.data?.byInstallation ?? {},
    );
  }, [integrations, repositoriesQuery.data]);

  /** Resolve the `UserIntegration` UUID for a selected installation id, to send
   *  as `github_user_integration` on task creation. */
  const getUserIntegrationId = useCallback(
    (installationId: number | null): string | undefined => {
      if (installationId == null) return undefined;
      return integrations.find(
        (i) => Number(i.installation_id) === installationId,
      )?.id;
    },
    [integrations],
  );

  const refetch = useCallback(async () => {
    if (!enabled) return;
    await integrationsQuery.refetch();
    await repositoriesQuery.refetch();
  }, [enabled, integrationsQuery, repositoriesQuery]);

  return {
    hasGithubIntegration: !enabled
      ? null
      : integrationsQuery.isFetched
        ? integrations.length > 0
        : null,
    integrations,
    repositoryOptions,
    getUserIntegrationId,
    // No persisted cache, so there is no "cached list while refreshing" state.
    isRefreshingInBackground: false,
    isLoading: enabled
      ? integrationsQuery.isLoading || repositoriesQuery.isLoading
      : false,
    error: enabled ? (integrationsQuery.error?.message ?? null) : null,
    repositoryWarning: enabled
      ? (repositoriesQuery.data?.partialError ?? null)
      : null,
    refetch,
  };
}
