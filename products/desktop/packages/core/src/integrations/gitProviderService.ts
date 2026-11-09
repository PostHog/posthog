import { inject, injectable } from "inversify";
import {
  type GitProviderConnection,
  type GitProviderKind,
  type GitProviderRepository,
  githubRepositories,
  gitlabRepository,
  gitProviderConnections,
  sortGitProviderRepositories,
} from "./gitProviders";
import { REPOSITORIES_SERVICE } from "./identifiers";
import type {
  RepositoryQueryResult,
  TeamRepositoriesResult,
} from "./repositories";
import type { RepositoriesService } from "./repositoriesService";
import {
  type RepositoryRefetchKey,
  teamRepositoryRefreshKeys,
} from "./repositoryKeys";
import type { Integration } from "./selectors";

export interface GitProviderRepositoriesResult {
  connections: GitProviderConnection[];
  repositories: GitProviderRepository[];
  failedConnections: GitProviderConnection[];
  pendingConnections: GitProviderConnection[];
}

export interface GitProviderRefreshResult {
  keys: RepositoryRefetchKey[];
  errors: unknown[];
}

@injectable()
export class GitProviderService {
  constructor(
    @inject(REPOSITORIES_SERVICE)
    private readonly repositories: RepositoriesService,
  ) {}

  combineRepositories(
    integrations: ReadonlyArray<Integration>,
    providers: ReadonlyArray<GitProviderKind>,
    githubResults: ReadonlyArray<RepositoryQueryResult<TeamRepositoriesResult>>,
  ): GitProviderRepositoriesResult {
    const connections = gitProviderConnections(integrations, providers);
    const repositories: GitProviderRepository[] = [];
    const failedConnections: GitProviderConnection[] = [];
    const pendingConnections: GitProviderConnection[] = [];
    let githubIndex = 0;

    for (const connection of connections) {
      if (connection.provider === "gitlab") {
        const integration = integrations.find(
          (item) => item.id === connection.integrationId,
        );
        const repository = integration && gitlabRepository(integration);
        if (repository) repositories.push(repository);
        continue;
      }
      const result = githubResults[githubIndex++];
      if (!result || result.isPending) pendingConnections.push(connection);
      if (result?.isError) failedConnections.push(connection);
      if (result?.data) {
        repositories.push(
          ...githubRepositories(
            connection.integrationId,
            result.data.repos ?? [],
          ),
        );
      }
    }

    return {
      connections,
      repositories: sortGitProviderRepositories(repositories),
      failedConnections,
      pendingConnections,
    };
  }

  async refreshRepositories(
    integrations: ReadonlyArray<Integration>,
  ): Promise<GitProviderRefreshResult> {
    const integrationIds = gitProviderConnections(integrations, ["github"]).map(
      (connection) => connection.integrationId,
    );
    const results = await Promise.allSettled(
      integrationIds.map((integrationId) =>
        this.repositories.refreshTeamRepositories([integrationId]),
      ),
    );
    const refreshedIds = integrationIds.filter(
      (_, index) => results[index]?.status === "fulfilled",
    );
    return {
      keys:
        refreshedIds.length > 0 ? teamRepositoryRefreshKeys(refreshedIds) : [],
      errors: results.flatMap((result) =>
        result.status === "rejected" ? [result.reason] : [],
      ),
    };
  }
}
