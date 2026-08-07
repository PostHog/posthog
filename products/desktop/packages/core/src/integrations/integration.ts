import {
  type IUrlLauncher,
  URL_LAUNCHER_SERVICE,
} from "@posthog/platform/url-launcher";
import { type CloudRegion, getCloudUrlFromRegion } from "@posthog/shared";
import { inject, injectable } from "inversify";
import type { StartIntegrationFlowOutput } from "./schemas";

/**
 * Generic OAuth integration flow starter. PostHog's
 * `…/integrations/authorize/?kind=<kind>` endpoint is generic over the integration kind, so a
 * single service starts the flow for any supported OAuth provider (linear, intercom, hubspot,
 * salesforce, …) — no per-kind service or router required. The OAuth grant, callback, and token
 * storage all happen on PostHog Cloud; the caller then polls the integrations list for the new
 * integration of this `kind`.
 */
@injectable()
export class IntegrationService {
  constructor(
    @inject(URL_LAUNCHER_SERVICE)
    private readonly urlLauncher: IUrlLauncher,
  ) {}

  public async startFlow(
    kind: string,
    region: CloudRegion,
    projectId: number,
  ): Promise<StartIntegrationFlowOutput> {
    try {
      const cloudUrl = getCloudUrlFromRegion(region);
      const next = `${cloudUrl}/project/${projectId}`;
      const authorizeUrl = `${cloudUrl}/api/environments/${projectId}/integrations/authorize/?kind=${encodeURIComponent(kind)}&next=${encodeURIComponent(next)}`;

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
