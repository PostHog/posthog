import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { useAuthStore } from "@/features/auth";
import { getGithubRepositories, getIntegrations } from "../api";
import { useRepositoryCacheStore } from "../stores/repositoryCacheStore";
import type { RepositoryOption } from "../types";
import { buildRepositoryOptions } from "../utils/repositorySelection";

/** Cheap content-equality check for repository option lists. Lets the cache
 *  write effect skip no-op updates, which is what kept retriggering renders
 *  before — `buildRepositoryOptions` always returns a fresh array, so the
 *  effect's dep array churned every render. */
function repositoryOptionsEqual(
  a: RepositoryOption[],
  b: RepositoryOption[],
): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    const left = a[i];
    const right = b[i];
    if (
      left.integrationId !== right.integrationId ||
      left.repository !== right.repository ||
      left.integrationLabel !== right.integrationLabel
    ) {
      return false;
    }
  }
  return true;
}

export const integrationKeys = {
  all: ["integrations"] as const,
  lists: () => [...integrationKeys.all, "list"] as const,
  github: () => [...integrationKeys.all, "github"] as const,
  repos: (integrationId: number) =>
    [...integrationKeys.all, "repos", integrationId] as const,
};

interface RepositoryLoadResult {
  repositoriesByIntegration: Record<number, string[]>;
  partialError: string | null;
}

interface UseIntegrationsOptions {
  enabled?: boolean;
}

export function useIntegrations(options: UseIntegrationsOptions = {}) {
  const { enabled = true } = options;
  const { projectId, oauthAccessToken } = useAuthStore();

  // Persisted snapshot from the last successful fetch. Survives app launches
  // so the picker can render instantly while we refetch in the background.
  const cachedOptions = useRepositoryCacheStore((s) => s.options);
  const setCachedOptions = useRepositoryCacheStore((s) => s.setOptions);

  const integrationsQuery = useQuery({
    queryKey: integrationKeys.github(),
    queryFn: async () => {
      const data = await getIntegrations();
      return data.filter((i) => i.kind === "github");
    },
    enabled: enabled && !!projectId && !!oauthAccessToken,
  });

  const githubIntegrations = enabled ? (integrationsQuery.data ?? []) : [];

  const repositoriesQuery = useQuery({
    queryKey: [
      ...integrationKeys.all,
      "repos",
      githubIntegrations.map((i) => i.id),
    ],
    queryFn: async (): Promise<RepositoryLoadResult> => {
      const repositoriesByIntegration: Record<number, string[]> = {};
      const results = await Promise.allSettled(
        githubIntegrations.map(async (integration) => ({
          integrationId: integration.id,
          repositories: await getGithubRepositories(integration.id),
        })),
      );

      let failedCount = 0;

      for (const result of results) {
        if (result.status === "fulfilled") {
          repositoriesByIntegration[result.value.integrationId] =
            result.value.repositories;
          continue;
        }

        failedCount += 1;
      }

      return {
        repositoriesByIntegration,
        partialError:
          failedCount === 0
            ? null
            : failedCount === githubIntegrations.length
              ? "Could not load GitHub repositories. Pull to retry."
              : "Some GitHub repositories could not be loaded. Pull to retry.",
      };
    },
    enabled: enabled && githubIntegrations.length > 0,
  });

  const repositoriesByIntegration =
    repositoriesQuery.data?.repositoriesByIntegration ?? {};
  const repositories = Object.values(repositoriesByIntegration).flat().sort();

  // Memoize the derived options list keyed on the underlying query data so
  // its reference is stable across renders when the data hasn't actually
  // changed. Without this, every render produces a fresh array — which both
  // churns the cache-write effect below AND defeats downstream React.memo /
  // useMemo callers that depend on `repositoryOptions`.
  const liveRepositoryOptions = useMemo(
    () => buildRepositoryOptions(githubIntegrations, repositoriesByIntegration),
    [githubIntegrations, repositoriesByIntegration],
  );

  // Mirror the latest successful fetch into the persisted cache so the next
  // cold start can render the picker instantly. We sync whatever the live
  // result is — including an empty array — but only once both queries have
  // succeeded, so a transient fetch failure or in-flight refresh can't wipe
  // out a working snapshot. Compare contents before writing so we don't
  // bump `updatedAt` (and re-render every cache subscriber) on no-op syncs.
  const integrationsSettled =
    integrationsQuery.isFetched && !integrationsQuery.isError;
  // biome-ignore lint/correctness/useExhaustiveDependencies: setCachedOptions is a stable Zustand action
  useEffect(() => {
    if (!enabled) return;
    if (!integrationsSettled) return;
    if (githubIntegrations.length === 0) {
      // No integrations — clear the cache so the picker doesn't surface
      // stale repos for a connection the user has since removed.
      if (cachedOptions.length > 0) setCachedOptions([]);
      return;
    }
    if (!repositoriesQuery.isSuccess) return;
    // Skip the write when the cache already matches — otherwise every
    // render that produces a structurally-equal options list (e.g. after
    // an unrelated re-render of the consumer) would push a new `updatedAt`,
    // re-trigger every cache subscriber, and the consumer's `useEffect`
    // would fire again on the new reference. Infinite loop.
    if (repositoryOptionsEqual(liveRepositoryOptions, cachedOptions)) return;
    setCachedOptions(liveRepositoryOptions);
  }, [
    enabled,
    integrationsSettled,
    githubIntegrations.length,
    repositoriesQuery.isSuccess,
    liveRepositoryOptions,
    cachedOptions,
  ]);

  // Prefer live data once it's in; fall back to the persisted snapshot so
  // consumers always have *something* to render on cold start.
  const repositoryOptions =
    liveRepositoryOptions.length > 0 ? liveRepositoryOptions : cachedOptions;
  const repositoryWarning = repositoriesQuery.data?.partialError ?? null;
  const hasCachedRepositories = cachedOptions.length > 0;

  const refetch = async () => {
    if (!enabled) {
      return;
    }

    await integrationsQuery.refetch();
    await repositoriesQuery.refetch();
  };

  return {
    hasGithubIntegration: !enabled
      ? null
      : integrationsQuery.isFetched
        ? githubIntegrations.length > 0
        : // If we have cached repos we know there's at least one integration,
          // so don't gate the screen on the integrations query.
          hasCachedRepositories
          ? true
          : null,
    githubIntegrations,
    repositories,
    repositoriesByIntegration,
    repositoryOptions,
    /** True iff we have cached options but the live fetch is still running.
     *  Lets the UI render the cached list while showing a subtle background
     *  refresh indicator instead of a blocking spinner. */
    isRefreshingInBackground:
      enabled &&
      hasCachedRepositories &&
      (integrationsQuery.isLoading || repositoriesQuery.isLoading),
    /** Only true when we have nothing to show yet — no cache, no live data.
     *  Consumers should treat this as "block the screen on a spinner";
     *  background refreshes don't count. */
    isLoading: enabled
      ? !hasCachedRepositories &&
        (integrationsQuery.isLoading || repositoriesQuery.isLoading)
      : false,
    error: enabled ? (integrationsQuery.error?.message ?? null) : null,
    repositoryWarning: enabled ? repositoryWarning : null,
    refetch,
  };
}
