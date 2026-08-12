import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { CspReportingContribution } from "./cspReporting.contribution";

export const cspReportingUiModule = new ContainerModule(({ bind }) => {
  bind(CONTRIBUTION).to(CspReportingContribution).inSingletonScope();
});
