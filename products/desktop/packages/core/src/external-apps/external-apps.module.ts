import { ContainerModule } from "inversify";
import { ExternalAppService } from "./externalAppService";
import { EXTERNAL_APPS_SERVICE } from "./identifiers";

export const externalAppsCoreModule = new ContainerModule(({ bind }) => {
  bind(EXTERNAL_APPS_SERVICE).to(ExternalAppService).inSingletonScope();
});
