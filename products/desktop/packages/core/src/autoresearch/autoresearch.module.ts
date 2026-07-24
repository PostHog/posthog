import { CONTRIBUTION } from "@posthog/di/contribution";
import { ContainerModule } from "inversify";
import { AutoresearchService } from "./autoresearch";
import { AutoresearchRehydrationContribution } from "./autoresearch.contribution";
import { AUTORESEARCH_SERVICE } from "./identifiers";

export const autoresearchCoreModule = new ContainerModule(({ bind }) => {
  bind(AUTORESEARCH_SERVICE).to(AutoresearchService).inSingletonScope();
  bind(CONTRIBUTION).to(AutoresearchRehydrationContribution).inSingletonScope();
});
