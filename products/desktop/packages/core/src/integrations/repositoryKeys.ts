export const integrationKeys = {
  all: ["integrations"] as const,
  list: () => [...integrationKeys.all, "list"] as const,
  repositories: (integrationId?: number) =>
    [...integrationKeys.all, "repositories", integrationId] as const,
  repositoryPicker: (integrationId?: number, search?: string, limit?: number) =>
    [
      ...integrationKeys.all,
      "repository-picker",
      integrationId,
      search,
      limit,
    ] as const,
  branches: (integrationId?: number, repo?: string | null, search?: string) =>
    [...integrationKeys.all, "branches", integrationId, repo, search] as const,
};

export const userGithubIntegrationKeys = {
  all: ["user-github-integrations"] as const,
  list: () => [...userGithubIntegrationKeys.all, "list"] as const,
  repositories: (installationId?: string) =>
    [...userGithubIntegrationKeys.all, "repositories", installationId] as const,
  repositoryPicker: (
    installationId?: string,
    search?: string,
    limit?: number,
  ) =>
    [
      ...userGithubIntegrationKeys.all,
      "repository-picker",
      installationId,
      search,
      limit,
    ] as const,
  branches: (installationId?: string, repo?: string | null, search?: string) =>
    [
      ...userGithubIntegrationKeys.all,
      "branches",
      installationId,
      repo,
      search,
    ] as const,
};

export interface RepositoryRefetchKey {
  queryKey: ReadonlyArray<unknown>;
  exact: boolean;
}

export function teamRepositoryRefreshKeys(
  integrationIds: ReadonlyArray<number>,
): RepositoryRefetchKey[] {
  const keys: RepositoryRefetchKey[] = integrationIds.map((integrationId) => ({
    queryKey: integrationKeys.repositories(integrationId),
    exact: true,
  }));
  keys.push({
    queryKey: [...integrationKeys.all, "repository-picker"],
    exact: false,
  });
  return keys;
}

export function userRepositoryRefreshKeys(
  installationIds: ReadonlyArray<string>,
): RepositoryRefetchKey[] {
  const keys: RepositoryRefetchKey[] = installationIds.map(
    (installationId) => ({
      queryKey: userGithubIntegrationKeys.repositories(installationId),
      exact: true,
    }),
  );
  keys.push({
    queryKey: [...userGithubIntegrationKeys.all, "repository-picker"],
    exact: false,
  });
  return keys;
}
