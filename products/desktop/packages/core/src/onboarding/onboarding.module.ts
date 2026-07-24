import { ContainerModule } from "inversify";
import { GithubConnectService } from "./githubConnectService";
import { GITHUB_CONNECT_SERVICE } from "./identifiers";

export const onboardingModule = new ContainerModule(({ bind }) => {
  bind(GITHUB_CONNECT_SERVICE).to(GithubConnectService).inSingletonScope();
});
