import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { MissionControlContribution } from "./missionControl.contribution";

export const missionControlUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(MissionControlContribution).inSingletonScope();
});
