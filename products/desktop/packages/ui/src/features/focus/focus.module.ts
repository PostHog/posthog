import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { FocusEventsContribution } from "./focus-events.contribution";

export const focusUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(FocusEventsContribution).inSingletonScope();
});
