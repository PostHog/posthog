import { ContainerModule } from "inversify";
import { GitHubIntegrationService } from "./github";
import {
  GITHUB_INTEGRATION_SERVICE,
  INTEGRATION_SERVICE,
  LINEAR_INTEGRATION_SERVICE,
  SLACK_INTEGRATION_SERVICE,
} from "./identifiers";
import { IntegrationService } from "./integration";
import { LinearIntegrationService } from "./linear";
import { SlackIntegrationService } from "./slack";

export const integrationsModule = new ContainerModule(({ bind }) => {
  bind(INTEGRATION_SERVICE).to(IntegrationService).inSingletonScope();
  bind(GITHUB_INTEGRATION_SERVICE)
    .to(GitHubIntegrationService)
    .inSingletonScope();
  bind(LINEAR_INTEGRATION_SERVICE)
    .to(LinearIntegrationService)
    .inSingletonScope();
  bind(SLACK_INTEGRATION_SERVICE)
    .to(SlackIntegrationService)
    .inSingletonScope();
});
