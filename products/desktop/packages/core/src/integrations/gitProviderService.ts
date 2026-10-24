import { inject, injectable } from "inversify";
import {
  type GitProviderConnection,
  type GitProviderKind,
  type GitProviderRepository,
  gitProviderConnections,
  githubRepositories,
  gitlabRepository,
  sortGitProviderRepositories,
} from "./gitProviders";
import { GIT_PROVIDER_CLIENT, type GitProviderClient } from "./identifiers";
import type { Integration } from "./selectors";

export interface GitProviderRepositoriesResult {
  connections: GitProviderConnection[];
  repositories: GitProviderRepository[];
  /** Connections whose repository list could not be read. The other connections still answer. */
  failedConnections: GitProviderConnection[];
}

/**
 * One read path over every source control provider the project is connected to. The caller
 * decides which providers are enabled (the GitLab flag lives in the UI layer), and the service
 * answers in one repository shape so a picker does not branch on the provider.
 */
@injectable()
export class GitProviderService {
  constructor(
    @inject(GIT_PROVIDER_CLIENT)
    private readonly client: GitProviderClient,
  ) {}

  async listRepositories(
    integrations: ReadonlyArray<Integration>,
    providers: ReadonlyArray<GitProviderKind>,
  ): Promise<GitProviderRepositoriesResult> {
    const connections = gitProviderConnections(integrations, providers);
    const byId = new Map(
      integrations.map((integration) => [integration.id, integration]),
    );

    const settled = await Promise.allSettled(
      connections.map((connection) => {
        const integration = byId.get(connection.integrationId);
        if (!integration) return Promise.resolve([]);
        return this.repositoriesFor(connection, integration);
      }),
    );

    const repositories: GitProviderRepository[] = [];
    const failedConnections: GitProviderConnection[] = [];
    settled.forEach((result, index) => {
      const connection = connections[index];
      if (!connection) return;
      if (result.status === "fulfilled") {
        repositories.push(...result.value);
      } else {
        failedConnections.push(connection);
      }
    });

    return {
      connections,
      repositories: sortGitProviderRepositories(repositories),
      failedConnections,
    };
  }

  private async repositoriesFor(
    connection: GitProviderConnection,
    integration: Integration,
  ): Promise<GitProviderRepository[]> {
    switch (connection.provider) {
      case "github":
        return githubRepositories(
          connection.integrationId,
          await this.client.listGithubRepositories(connection.integrationId),
        );
      case "gitlab": {
        const repository = gitlabRepository(integration);
        return repository ? [repository] : [];
      }
    }
  }
}
