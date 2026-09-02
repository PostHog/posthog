import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { CloneContribution } from "./clone.contribution";

export const cloneUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(CloneContribution).inSingletonScope();
});
