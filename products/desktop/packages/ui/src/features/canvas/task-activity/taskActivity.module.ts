import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { DockBadgeContribution } from "./dockBadge.contribution";
import { TaskActivityContribution } from "./taskActivity.contribution";

export const taskActivityUiModule = new ContainerModule(({ bind }) => {
  bind(TaskActivityContribution).toSelf().inSingletonScope();
  bind(CONTRIBUTION).toService(TaskActivityContribution);
  bind(DockBadgeContribution).toSelf().inSingletonScope();
  bind(CONTRIBUTION).toService(DockBadgeContribution);
});
