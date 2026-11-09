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
import type { Integration } from "./selectors";

export interface GitProviderRepositoriesResult {
  connections: GitProviderConnection[];
  repositories: GitProviderRepository[];
  failedConnections: GitProviderConnection[];
  pendingConnections: GitProviderConnection[];
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

  refreshRepositories(integrations: ReadonlyArray<Integration>) {
    return this.repositories.refreshTeamRepositoriesAndKeys(
      gitProviderConnections(integrations, ["github"]).map(
        (connection) => connection.integrationId,
      ),
    );
  }
}
