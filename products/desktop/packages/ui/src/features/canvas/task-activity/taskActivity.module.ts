import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { TaskActivityContribution } from "./taskActivity.contribution";

export const taskActivityUiModule = new ContainerModule(({ bind }) => {
  bind(TaskActivityContribution).toSelf().inSingletonScope();
  bind(CONTRIBUTION).toService(TaskActivityContribution);
});
