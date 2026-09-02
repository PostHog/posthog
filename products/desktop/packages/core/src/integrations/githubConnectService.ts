import { inject, injectable } from "inversify";
import {
  computeShouldUseTeamFlow,
  validateInstallUrl,
} from "./connectEligibility";
import { GITHUB_CONNECT_CLIENT, type GithubConnectClient } from "./identifiers";

export interface ConnectInput {
  projectId: number;
  isAdmin: boolean | null;
  projectHasTeamIntegration: boolean | null;
  cloudRegion: string | null;
}

export interface ConnectOutcome {
  flow: "team" | "user";
}

@injectable()
export class GithubConnectService {
  constructor(
    @inject(GITHUB_CONNECT_CLIENT)
    private readonly client: GithubConnectClient,
  ) {}

  async connect(input: ConnectInput): Promise<ConnectOutcome> {
    const useTeamFlow = computeShouldUseTeamFlow({
      isAdmin: input.isAdmin,
      projectHasTeamIntegration: input.projectHasTeamIntegration,
      cloudRegion: input.cloudRegion,
    });

    if (useTeamFlow && input.cloudRegion) {
      const result = await this.client.startTeamFlow({
        region: input.cloudRegion,
        projectId: input.projectId,
      });
      if (!result.success) {
        throw new Error(result.error ?? "Failed to start GitHub connection");
      }
      return { flow: "team" };
    }

    await this.runUserFlow(input.projectId);
    return { flow: "user" };
  }

  async connectUser(projectId: number): Promise<ConnectOutcome> {
    await this.runUserFlow(projectId);
    return { flow: "user" };
  }

  private async runUserFlow(projectId: number): Promise<void> {
    const res = await this.client.startUserConnect(projectId);
    const installUrl = validateInstallUrl(res.install_url);
    await this.client.launchUrl(installUrl);
  }
}
