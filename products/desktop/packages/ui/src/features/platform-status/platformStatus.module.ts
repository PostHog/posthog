import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { PlatformStatusContribution } from "./platformStatus.contribution";

export const platformStatusUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(PlatformStatusContribution).inSingletonScope();
});
