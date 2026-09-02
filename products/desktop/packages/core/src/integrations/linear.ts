import {
  type IUrlLauncher,
  URL_LAUNCHER_SERVICE,
} from "@posthog/platform/url-launcher";
import { type CloudRegion, getCloudUrlFromRegion } from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { StartIntegrationFlowOutput } from "./schemas";

@injectable()
export class LinearIntegrationService {
  constructor(
    @inject(URL_LAUNCHER_SERVICE)
    private readonly urlLauncher: IUrlLauncher,
  ) {}

  public async startFlow(
    region: CloudRegion,
    projectId: number,
  ): Promise<StartIntegrationFlowOutput> {
    try {
      const cloudUrl = getCloudUrlFromRegion(region);
      const next = `${cloudUrl}/project/${projectId}`;
      const authorizeUrl = `${cloudUrl}/api/environments/${projectId}/integrations/authorize/?kind=linear&next=${encodeURIComponent(next)}`;

      await this.urlLauncher.launch(authorizeUrl);

      return { success: true };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : "Unknown error",
      };
    }
  }
}
