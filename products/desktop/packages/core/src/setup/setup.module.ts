import { SetupRunService } from "@posthog/core/setup/setupRunService";
import { ContainerModule } from "inversify";

export const setupCoreModule = new ContainerModule(({ bind }) => {
  bind(SetupRunService).toSelf().inSingletonScope();
});
