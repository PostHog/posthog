import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { BrowserTabsEventsContribution } from "./browser-tabs-events.contribution";

export const browserTabsUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(BrowserTabsEventsContribution).inSingletonScope();
});
