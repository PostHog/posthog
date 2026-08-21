import { inject, injectable } from "inversify";
import { REPOSITORIES_CLIENT, type RepositoriesClient } from "./identifiers";
import {
  type RepositoryRefetchKey,
  teamRepositoryRefreshKeys,
  userRepositoryRefreshKeys,
} from "./repositoryKeys";

@injectable()
export class RepositoriesService {
  constructor(
    @inject(REPOSITORIES_CLIENT)
    private readonly client: RepositoriesClient,
  ) {}

  async refreshTeamRepositories(integrationIds: number[]): Promise<void> {
    if (integrationIds.length === 0) {
      return;
    }
    await Promise.all(
      integrationIds.map((integrationId) =>
        this.client.refreshTeamRepository(integrationId),
      ),
    );
  }

  async refreshUserRepositories(installationIds: string[]): Promise<void> {
    if (installationIds.length === 0) {
      return;
    }
    await Promise.all(
      installationIds.map((installationId) =>
        this.client.refreshUserRepository(installationId),
      ),
    );
  }

  async refreshTeamRepositoriesAndKeys(
    integrationIds: number[],
  ): Promise<RepositoryRefetchKey[]> {
    await this.refreshTeamRepositories(integrationIds);
    return teamRepositoryRefreshKeys(integrationIds);
  }

  async refreshUserRepositoriesAndKeys(
    installationIds: string[],
  ): Promise<RepositoryRefetchKey[]> {
    await this.refreshUserRepositories(installationIds);
    return userRepositoryRefreshKeys(installationIds);
  }
}
