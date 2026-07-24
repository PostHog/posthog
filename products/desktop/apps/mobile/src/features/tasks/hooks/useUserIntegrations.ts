import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { useAuthStore } from "@/features/auth";
import { getUserGithubIntegrations, getUserGithubRepositories } from "../api";
import type { RepositoryOption, UserGithubIntegration } from "../types";

/**
 * User-scoped sibling of {@link useIntegrations}. Reads the authenticated
 * user's personal GitHub integrations (`/api/users/@me/integrations/`) rather
 * than the team-level ones, matching how the desktop app links GitHub per user.
 *
 * Used by the interactive task-creation flow (new task screen, task list empty
 * state, connect prompt). Automations stay on {@link useIntegrations} because
 * they run server-side without a user and need the team integration.
 *
 * Repos are keyed by the numeric GitHub `installation_id` so the existing
 * number-based picker/`RepositoryOption` keep working; `getUserIntegrationId`
 * maps that back to the `UserIntegration` UUID for task creation. No persisted
 * cache here (unlike the team hook) so it can't clobber the automations cache.
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

function integrationLabel(integration: UserGithubIntegration): string {
  return integration.account?.name ?? `GitHub ${integration.installation_id}`;
}

export function useUserIntegrations(options: UseUserIntegrationsOptions = {}) {
  const { enabled = true } = options;
  const { oauthAccessToken } = useAuthStore();

  const integrationsQuery = useQuery({
    queryKey: userIntegrationKeys.github(),
    queryFn: getUserGithubIntegrations,
    enabled: enabled && !!oauthAccessToken,
  });

  const integrations = enabled ? (integrationsQuery.data ?? []) : [];

  const repositoriesQuery = useQuery({
    queryKey: userIntegrationKeys.repos(
      integrations.map((i) => i.installation_id),
    ),
    queryFn: async () => {
      const byInstallation: Record<string, string[]> = {};
      const results = await Promise.allSettled(
        integrations.map(async (integration) => ({
          installationId: integration.installation_id,
          repositories: await getUserGithubRepositories(
            integration.installation_id,
          ),
        })),
      );

      let failedCount = 0;
      for (const result of results) {
        if (result.status === "fulfilled") {
          byInstallation[result.value.installationId] =
            result.value.repositories;
        } else {
          failedCount += 1;
        }
      }

      return {
        byInstallation,
        partialError:
          failedCount === 0
            ? null
            : failedCount === integrations.length
              ? "Could not load GitHub repositories. Pull to retry."
              : "Some GitHub repositories could not be loaded. Pull to retry.",
      };
    },
    enabled: enabled && integrations.length > 0,
  });

  const repositoryOptions = useMemo<RepositoryOption[]>(() => {
    const byInstallation = repositoriesQuery.data?.byInstallation ?? {};
    return integrations
      .flatMap((integration) => {
        const repositories = byInstallation[integration.installation_id] ?? [];
        return repositories.map((repository) => ({
          // GitHub installation ids fit in a JS number; use it as the numeric
          // key the picker/RepositoryOption already expect.
          integrationId: Number(integration.installation_id),
          integrationLabel: integrationLabel(integration),
          repository,
        }));
      })
      .sort((left, right) => left.repository.localeCompare(right.repository));
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
