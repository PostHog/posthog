import type { UserGitHubIntegration } from "@posthog/api-client/posthog-client";
import {
  branchPageSizeForOffset,
  computeNextBranchOffset,
  flattenBranchPages,
  type GithubBranchesPage,
} from "@posthog/core/integrations/branches";
import { REPOSITORIES_SERVICE } from "@posthog/core/integrations/identifiers";
import {
  combineGithubRepositories,
  combineRepositoryPicker,
  combineUserGithubRepositories,
  getIntegrationIdForRepo,
  getRepoEntry,
  isEmptyRepositoryMap,
  isRepoInIntegration,
  resolveEffectiveUserRepositoryMap,
  resolveUserRepositoryCacheAction,
  type UserRepositoryIntegrationRef,
} from "@posthog/core/integrations/repositories";
import type { RepositoriesService } from "@posthog/core/integrations/repositoriesService";
import {
  integrationKeys,
  type RepositoryRefetchKey,
  userGithubIntegrationKeys,
} from "@posthog/core/integrations/repositoryKeys";
import { useService } from "@posthog/di/react";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import {
  type Integration,
  useIntegrationSelectors,
  useIntegrationStore,
} from "@posthog/ui/features/integrations/store";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useAuthenticatedInfiniteQuery } from "@posthog/ui/hooks/useAuthenticatedInfiniteQuery";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useDebounce } from "@posthog/ui/primitives/hooks/useDebounce";
import {
  type QueryClient,
  useQueries,
  useQueryClient,
} from "@tanstack/react-query";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";

// Branch search hits a slow remote endpoint (GitHub via PostHog proxy). Debounce
// keystrokes so we fire at most one request per typing burst. Empty searches
// skip the debounce so closing the picker (which resets search to "") clears
// stale results immediately.
const BRANCH_SEARCH_DEBOUNCE_MS = 300;

async function refetchRepositoryKeys(
  queryClient: QueryClient,
  keys: ReadonlyArray<RepositoryRefetchKey>,
): Promise<void> {
  await Promise.all(
    keys.map(({ queryKey, exact }) =>
      queryClient.refetchQueries({ queryKey: [...queryKey], exact }),
    ),
  );
}

export function useIntegrations() {
  const setIntegrations = useIntegrationStore((state) => state.setIntegrations);

  const query = useAuthenticatedQuery(
    integrationKeys.list(),
    (client) => client.getIntegrations() as Promise<Integration[]>,
  );

  useEffect(() => {
    if (query.data) {
      setIntegrations(query.data);
    }
  }, [query.data, setIntegrations]);

  return query;
}

function useAllGithubRepositories(githubIntegrations: Integration[]) {
  const client = useOptionalAuthenticatedClient();

  return useQueries({
    queries: githubIntegrations.map((integration) => ({
      queryKey: integrationKeys.repositories(integration.id),
      queryFn: async () => {
        if (!client) throw new Error("Not authenticated");
        const repos = await client.getGithubRepositories(integration.id);
        return { integrationId: integration.id, repos };
      },
      enabled: !!client,
      staleTime: 5 * 60 * 1000,
      meta: AUTH_SCOPED_QUERY_META,
    })),
    combine: combineGithubRepositories,
  });
}

export function useUserGithubIntegrations() {
  return useAuthenticatedQuery(userGithubIntegrationKeys.list(), (client) =>
    client.getGithubUserIntegrations(),
  );
}

function useAllUserGithubRepositories(
  githubIntegrations: UserGitHubIntegration[],
) {
  const client = useOptionalAuthenticatedClient();

  return useQueries({
    queries: githubIntegrations.map((integration) => ({
      queryKey: userGithubIntegrationKeys.repositories(
        integration.installation_id,
      ),
      queryFn: async () => {
        if (!client) throw new Error("Not authenticated");
        const repos = await client.getGithubUserRepositories(
          integration.installation_id,
        );
        return {
          userIntegrationId: integration.id,
          installationId: integration.installation_id,
          repos,
        };
      },
      enabled: !!client,
      staleTime: 5 * 60 * 1000,
      meta: AUTH_SCOPED_QUERY_META,
    })),
    combine: (results) =>
      combineUserGithubRepositories(
        results,
        githubIntegrations.map((i) => i.installation_id),
      ),
  });
}

const REPOSITORIES_PAGE_SIZE = 50;

export function useGithubRepositories(
  search?: string,
  enabled: boolean = true,
) {
  const client = useOptionalAuthenticatedClient();
  const { githubIntegrations } = useIntegrationSelectors();
  const deferredSearch = useDeferredValue(search?.trim() ?? "");
  const [requestedLimit, setRequestedLimit] = useState(REPOSITORIES_PAGE_SIZE);
  const queryEnabled = enabled && !!client && githubIntegrations.length > 0;

  useEffect(() => {
    setRequestedLimit(REPOSITORIES_PAGE_SIZE);
  }, []);

  const { repositoryMap, isPending, isRefreshing, hasMore } = useQueries({
    queries: githubIntegrations.map((integration) => ({
      queryKey: integrationKeys.repositoryPicker(
        integration.id,
        deferredSearch,
        requestedLimit,
      ),
      queryFn: async () => {
        if (!client) throw new Error("Not authenticated");

        const page = await client.getGithubRepositoriesPage(
          integration.id,
          0,
          requestedLimit,
          deferredSearch,
        );

        return { ref: integration.id, ...page };
      },
      enabled: queryEnabled,
      staleTime: 5 * 60 * 1000,
      placeholderData: (prev: unknown) => prev,
      meta: AUTH_SCOPED_QUERY_META,
    })),
    combine: combineRepositoryPicker<number>,
  });

  const loadMore = useCallback(() => {
    setRequestedLimit((currentLimit) => currentLimit + REPOSITORIES_PAGE_SIZE);
  }, []);

  return {
    repositories: Object.keys(repositoryMap),
    isPending: queryEnabled ? isPending : false,
    isRefreshing: queryEnabled ? isRefreshing : false,
    hasMore,
    loadMore,
  };
}

export function useUserGithubRepositories(
  search?: string,
  enabled: boolean = true,
) {
  const client = useOptionalAuthenticatedClient();
  const { data: githubIntegrations = [] } = useUserGithubIntegrations();
  const deferredSearch = useDeferredValue(search?.trim() ?? "");
  const [requestedLimit, setRequestedLimit] = useState(REPOSITORIES_PAGE_SIZE);
  const queryEnabled = enabled && !!client && githubIntegrations.length > 0;

  useEffect(() => {
    setRequestedLimit(REPOSITORIES_PAGE_SIZE);
  }, []);

  const { repositoryMap, isPending, isRefreshing, hasMore } = useQueries({
    queries: githubIntegrations.map((integration) => ({
      queryKey: userGithubIntegrationKeys.repositoryPicker(
        integration.installation_id,
        deferredSearch,
        requestedLimit,
      ),
      queryFn: async () => {
        if (!client) throw new Error("Not authenticated");

        const page = await client.getGithubUserRepositoriesPage(
          integration.installation_id,
          0,
          requestedLimit,
          deferredSearch,
        );

        return {
          ref: {
            userIntegrationId: integration.id,
            installationId: integration.installation_id,
          },
          ...page,
        };
      },
      enabled: queryEnabled,
      staleTime: 5 * 60 * 1000,
      meta: AUTH_SCOPED_QUERY_META,
    })),
    combine: combineRepositoryPicker<UserRepositoryIntegrationRef>,
  });

  const loadMore = useCallback(() => {
    setRequestedLimit((currentLimit) => currentLimit + REPOSITORIES_PAGE_SIZE);
  }, []);

  return {
    repositories: Object.keys(repositoryMap),
    isPending: queryEnabled ? isPending : false,
    isRefreshing: queryEnabled ? isRefreshing : false,
    hasMore,
    loadMore,
  };
}

export function useGithubBranches(
  integrationId?: number,
  repo?: string | null,
  search?: string,
  enabled: boolean = true,
) {
  const trimmedSearch = search?.trim() ?? "";
  const debouncedSearch = useDebounce(
    trimmedSearch,
    trimmedSearch ? BRANCH_SEARCH_DEBOUNCE_MS : 0,
  );
  const queryEnabled = enabled && !!integrationId && !!repo;

  const query = useAuthenticatedInfiniteQuery<GithubBranchesPage, number>(
    integrationKeys.branches(integrationId, repo, debouncedSearch),
    async (client, offset) => {
      if (!integrationId || !repo) {
        return { branches: [], defaultBranch: null, hasMore: false };
      }
      return await client.getGithubBranchesPage(
        integrationId,
        repo,
        offset,
        branchPageSizeForOffset(offset),
        debouncedSearch,
      );
    },
    {
      enabled: queryEnabled,
      initialPageParam: 0,
      getNextPageParam: computeNextBranchOffset,
      staleTime: 5 * 60 * 1000,
    },
  );

  const data = useMemo(
    () => flattenBranchPages(query.data?.pages),
    [query.data?.pages],
  );

  const loadMore = useCallback(() => {
    if (!query.hasNextPage || query.isFetchingNextPage) {
      return;
    }

    void query.fetchNextPage();
  }, [query.fetchNextPage, query.hasNextPage, query.isFetchingNextPage]);

  const refresh = useCallback(async () => {
    await query.refetch();
  }, [query.refetch]);

  return {
    data,
    isPending: queryEnabled ? query.isPending : false,
    isRefreshing: queryEnabled ? query.isRefetching : false,
    isFetchingMore: query.isFetchingNextPage,
    hasMore: query.hasNextPage ?? false,
    loadMore,
    refresh,
  };
}

export function useUserGithubBranches(
  installationId?: string,
  repo?: string | null,
  search?: string,
  enabled: boolean = true,
) {
  const trimmedSearch = search?.trim() ?? "";
  const debouncedSearch = useDebounce(
    trimmedSearch,
    trimmedSearch ? BRANCH_SEARCH_DEBOUNCE_MS : 0,
  );
  const queryEnabled = enabled && !!installationId && !!repo;

  const query = useAuthenticatedInfiniteQuery<GithubBranchesPage, number>(
    userGithubIntegrationKeys.branches(installationId, repo, debouncedSearch),
    async (client, offset) => {
      if (!installationId || !repo) {
        return { branches: [], defaultBranch: null, hasMore: false };
      }
      return await client.getGithubUserBranchesPage(
        installationId,
        repo,
        offset,
        branchPageSizeForOffset(offset),
        debouncedSearch,
      );
    },
    {
      enabled: queryEnabled,
      initialPageParam: 0,
      getNextPageParam: computeNextBranchOffset,
      staleTime: 5 * 60 * 1000,
    },
  );

  const data = useMemo(
    () => flattenBranchPages(query.data?.pages),
    [query.data?.pages],
  );

  const loadMore = useCallback(() => {
    if (!query.hasNextPage || query.isFetchingNextPage) {
      return;
    }

    void query.fetchNextPage();
  }, [query.fetchNextPage, query.hasNextPage, query.isFetchingNextPage]);

  const refresh = useCallback(async () => {
    await query.refetch();
  }, [query.refetch]);

  return {
    data,
    isPending: queryEnabled ? query.isPending : false,
    isRefreshing: queryEnabled ? query.isRefetching : false,
    isFetchingMore: query.isFetchingNextPage,
    hasMore: query.hasNextPage ?? false,
    loadMore,
    refresh,
  };
}

export function useUserRepositoryIntegration() {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const repositoriesService =
    useService<RepositoriesService>(REPOSITORIES_SERVICE);
  const { data: githubIntegrations = [], isPending: integrationsPending } =
    useUserGithubIntegrations();
  const [isRefreshingRepos, setIsRefreshingRepos] = useState(false);

  const cachedRepositoryMap = useSettingsStore(
    (state) => state.cachedCloudRepositoryMap,
  );
  const setCachedRepositoryMap = useSettingsStore(
    (state) => state.setCachedCloudRepositoryMap,
  );

  const {
    repositoryMap,
    reposByInstallationId,
    isPending: reposPending,
    failedInstallationIds,
  } = useAllUserGithubRepositories(githubIntegrations);

  // Persist the freshly loaded map so the picker has data on the next cold
  // start, and clear it once the user has no integrations.
  const reposErrored = failedInstallationIds.length > 0;
  useEffect(() => {
    const action = resolveUserRepositoryCacheAction({
      integrationsPending,
      reposPending,
      reposErrored,
      hasIntegrations: githubIntegrations.length > 0,
      liveRepositoryMap: repositoryMap,
      cachedRepositoryMap,
    });
    if (action === "write") {
      setCachedRepositoryMap(repositoryMap);
    } else if (action === "clear") {
      setCachedRepositoryMap({});
    }
  }, [
    integrationsPending,
    reposPending,
    reposErrored,
    githubIntegrations.length,
    repositoryMap,
    cachedRepositoryMap,
    setCachedRepositoryMap,
  ]);

  const liveLoading = integrationsPending || reposPending;
  const { effectiveRepositoryMap, servingFromCache } =
    resolveEffectiveUserRepositoryMap({
      liveLoading,
      liveRepositoryMap: repositoryMap,
      cachedRepositoryMap,
    });

  const repositories = useMemo(
    () => Object.keys(effectiveRepositoryMap),
    [effectiveRepositoryMap],
  );

  const getUserIntegrationIdForRepo = useCallback(
    (repoKey: string) =>
      getRepoEntry(effectiveRepositoryMap, repoKey)?.userIntegrationId,
    [effectiveRepositoryMap],
  );

  const getInstallationIdForRepo = useCallback(
    (repoKey: string) =>
      getRepoEntry(effectiveRepositoryMap, repoKey)?.installationId,
    [effectiveRepositoryMap],
  );

  const repoInIntegration = useCallback(
    (repoKey: string) => isRepoInIntegration(effectiveRepositoryMap, repoKey),
    [effectiveRepositoryMap],
  );

  const refreshRepositories = useCallback(async () => {
    if (!githubIntegrations.length || !client) {
      return;
    }

    setIsRefreshingRepos(true);

    try {
      const refetchKeys =
        await repositoriesService.refreshUserRepositoriesAndKeys(
          githubIntegrations.map((integration) => integration.installation_id),
        );
      await refetchRepositoryKeys(queryClient, refetchKeys);
    } finally {
      setIsRefreshingRepos(false);
    }
  }, [client, githubIntegrations, queryClient, repositoriesService]);

  return {
    repositories,
    getUserIntegrationIdForRepo,
    getInstallationIdForRepo,
    isRepoInIntegration: repoInIntegration,
    isLoadingRepos: liveLoading && !servingFromCache,
    isRefreshingRepos: isRefreshingRepos || servingFromCache,
    refreshRepositories,
    hasGithubIntegration:
      githubIntegrations.length > 0 ||
      (integrationsPending && !isEmptyRepositoryMap(cachedRepositoryMap)),
    failedInstallationIds,
    reposByInstallationId,
  };
}

export function useRepositoryIntegration() {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const repositoriesService =
    useService<RepositoriesService>(REPOSITORIES_SERVICE);
  const { isPending: integrationsPending } = useIntegrations();
  const { githubIntegrations, hasGithubIntegration } =
    useIntegrationSelectors();
  const [isRefreshingRepos, setIsRefreshingRepos] = useState(false);

  const { repositoryMap, isPending: reposPending } =
    useAllGithubRepositories(githubIntegrations);

  const repositories = useMemo(
    () => Object.keys(repositoryMap),
    [repositoryMap],
  );

  const getIntegrationIdForRepoFn = useCallback(
    (repoKey: string) => getIntegrationIdForRepo(repositoryMap, repoKey),
    [repositoryMap],
  );

  const repoInIntegration = useCallback(
    (repoKey: string) => isRepoInIntegration(repositoryMap, repoKey),
    [repositoryMap],
  );

  const refreshRepositories = useCallback(async () => {
    if (!githubIntegrations.length || !client) {
      return;
    }

    setIsRefreshingRepos(true);

    try {
      const refetchKeys =
        await repositoriesService.refreshTeamRepositoriesAndKeys(
          githubIntegrations.map((integration) => integration.id),
        );
      await refetchRepositoryKeys(queryClient, refetchKeys);
    } finally {
      setIsRefreshingRepos(false);
    }
  }, [client, githubIntegrations, queryClient, repositoriesService]);

  return {
    repositories,
    getIntegrationIdForRepo: getIntegrationIdForRepoFn,
    isRepoInIntegration: repoInIntegration,
    isLoadingIntegrations: integrationsPending,
    isLoadingRepos: integrationsPending || reposPending,
    isRefreshingRepos,
    refreshRepositories,
    hasGithubIntegration,
  };
}
