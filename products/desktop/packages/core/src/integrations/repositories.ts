export interface RepositoryQueryResult<TData> {
  data: TData | undefined;
  isPending: boolean;
  isError: boolean;
  isRefetching: boolean;
}

export interface TeamRepositoriesResult {
  integrationId: number;
  repos?: string[] | null;
}

export interface CombinedTeamRepositories {
  repositoryMap: Record<string, number>;
  isPending: boolean;
}

export function combineGithubRepositories(
  results: ReadonlyArray<RepositoryQueryResult<TeamRepositoriesResult>>,
): CombinedTeamRepositories {
  const map: Record<string, number> = {};
  let pending = false;
  for (const result of results) {
    if (result.isPending) pending = true;
    if (!result.data) continue;
    for (const repo of result.data.repos ?? []) {
      if (!(repo in map)) {
        map[repo] = result.data.integrationId;
      }
    }
  }
  return { repositoryMap: map, isPending: pending };
}

export interface UserRepositoryIntegrationRef {
  userIntegrationId: string;
  installationId: string;
}

export interface UserRepositoriesResult {
  userIntegrationId: string;
  installationId: string;
  repos?: string[] | null;
}

export interface CombinedUserRepositories {
  repositoryMap: Record<string, UserRepositoryIntegrationRef>;
  reposByInstallationId: Record<string, string[]>;
  isPending: boolean;
  failedInstallationIds: string[];
}

export function combineUserGithubRepositories(
  results: ReadonlyArray<RepositoryQueryResult<UserRepositoriesResult>>,
  installationIds: ReadonlyArray<string | null | undefined>,
): CombinedUserRepositories {
  const map: Record<string, UserRepositoryIntegrationRef> = {};
  const reposByInstallationId: Record<string, string[]> = {};
  const failedInstallationIds: string[] = [];
  let pending = false;

  results.forEach((result, index) => {
    if (result.isPending) pending = true;
    if (result.isError) {
      const installationId = installationIds[index] ?? null;
      if (installationId) failedInstallationIds.push(installationId);
    }
    if (!result.data) return;
    const installationRepos = result.data.repos ?? [];
    reposByInstallationId[result.data.installationId] = installationRepos;
    for (const repo of installationRepos) {
      if (!(repo in map)) {
        map[repo] = {
          userIntegrationId: result.data.userIntegrationId,
          installationId: result.data.installationId,
        };
      }
    }
  });

  return {
    repositoryMap: map,
    reposByInstallationId,
    isPending: pending,
    failedInstallationIds,
  };
}

export interface RepositoryPageResult<TRef> {
  ref: TRef;
  repositories?: string[] | null;
  hasMore?: boolean;
}

export interface CombinedRepositoryPicker<TRef> {
  repositoryMap: Record<string, TRef>;
  isPending: boolean;
  isRefreshing: boolean;
  hasMore: boolean;
}

export function combineRepositoryPicker<TRef>(
  results: ReadonlyArray<RepositoryQueryResult<RepositoryPageResult<TRef>>>,
): CombinedRepositoryPicker<TRef> {
  const map: Record<string, TRef> = {};
  let pending = false;
  let refreshing = false;
  let hasMoreResults = false;

  for (const result of results) {
    if (result.isPending) pending = true;
    if (result.isRefetching) refreshing = true;
    if (!result.data) continue;

    if (result.data.hasMore) {
      hasMoreResults = true;
    }

    for (const repo of result.data.repositories ?? []) {
      if (!(repo in map)) {
        map[repo] = result.data.ref;
      }
    }
  }

  return {
    repositoryMap: map,
    isPending: pending,
    isRefreshing: refreshing,
    hasMore: hasMoreResults,
  };
}

export function normalizeRepoKey(repoKey: string | null | undefined): string {
  return repoKey?.toLowerCase() ?? "";
}

export function getRepoEntry<TRef>(
  repositoryMap: Record<string, TRef>,
  repoKey: string,
): TRef | undefined {
  return repositoryMap[normalizeRepoKey(repoKey)];
}

export function getIntegrationIdForRepo(
  repositoryMap: Record<string, number>,
  repoKey: string,
): number | undefined {
  return repositoryMap[normalizeRepoKey(repoKey)];
}

export function isRepoInIntegration(
  repositoryMap: Record<string, unknown>,
  repoKey: string,
): boolean {
  return !repoKey || normalizeRepoKey(repoKey) in repositoryMap;
}

export function isEmptyRepositoryMap(map: Record<string, unknown>): boolean {
  return Object.keys(map).length === 0;
}

export function sameUserRepositoryMap(
  a: Record<string, UserRepositoryIntegrationRef>,
  b: Record<string, UserRepositoryIntegrationRef>,
): boolean {
  const keys = Object.keys(a);
  if (keys.length !== Object.keys(b).length) return false;
  return keys.every((key) => {
    const left = a[key];
    const right = b[key];
    return (
      !!right &&
      left.userIntegrationId === right.userIntegrationId &&
      left.installationId === right.installationId
    );
  });
}

export type RepositoryCacheAction = "write" | "clear" | "skip";

export interface UserRepositoryCacheInputs {
  integrationsPending: boolean;
  reposPending: boolean;
  reposErrored: boolean;
  hasIntegrations: boolean;
  liveRepositoryMap: Record<string, UserRepositoryIntegrationRef>;
  cachedRepositoryMap: Record<string, UserRepositoryIntegrationRef>;
}

/**
 * Decides how the persisted cold-start cache should track the live repository
 * map: write fresh data, clear stale data, or leave the cache untouched.
 */
export function resolveUserRepositoryCacheAction({
  integrationsPending,
  reposPending,
  reposErrored,
  hasIntegrations,
  liveRepositoryMap,
  cachedRepositoryMap,
}: UserRepositoryCacheInputs): RepositoryCacheAction {
  if (integrationsPending) return "skip";
  if (!hasIntegrations) {
    return isEmptyRepositoryMap(cachedRepositoryMap) ? "skip" : "clear";
  }
  if (reposPending) return "skip";
  if (isEmptyRepositoryMap(liveRepositoryMap)) {
    // A failed fetch can return an empty map, so keep the last-known-good
    // cache instead of clobbering it. A genuinely empty result clears the
    // stale cache so a removed repo does not flash on the next cold start.
    if (reposErrored) return "skip";
    return isEmptyRepositoryMap(cachedRepositoryMap) ? "skip" : "clear";
  }
  if (sameUserRepositoryMap(liveRepositoryMap, cachedRepositoryMap)) {
    return "skip";
  }
  return "write";
}

export interface EffectiveUserRepositoryMap {
  effectiveRepositoryMap: Record<string, UserRepositoryIntegrationRef>;
  servingFromCache: boolean;
}

/**
 * Picks the map the picker should render: the cached map stands in only while
 * the live queries are loading and have produced nothing yet.
 */
export function resolveEffectiveUserRepositoryMap({
  liveLoading,
  liveRepositoryMap,
  cachedRepositoryMap,
}: {
  liveLoading: boolean;
  liveRepositoryMap: Record<string, UserRepositoryIntegrationRef>;
  cachedRepositoryMap: Record<string, UserRepositoryIntegrationRef>;
}): EffectiveUserRepositoryMap {
  const servingFromCache =
    liveLoading &&
    isEmptyRepositoryMap(liveRepositoryMap) &&
    !isEmptyRepositoryMap(cachedRepositoryMap);
  return {
    effectiveRepositoryMap: servingFromCache
      ? cachedRepositoryMap
      : liveRepositoryMap,
    servingFromCache,
  };
}
