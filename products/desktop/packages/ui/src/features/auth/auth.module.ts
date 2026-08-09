import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { AuthContribution } from "./auth.contribution";

export const authUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(AuthContribution).inSingletonScope();
});
