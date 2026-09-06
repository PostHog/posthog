import { ContainerModule } from "inversify";
import { PLATFORM_STATUS_SERVICE } from "./identifiers";
import { PlatformStatusService } from "./platformStatusService";

export const platformStatusCoreModule = new ContainerModule(({ bind }) => {
  bind(PLATFORM_STATUS_SERVICE).to(PlatformStatusService).inSingletonScope();
});
