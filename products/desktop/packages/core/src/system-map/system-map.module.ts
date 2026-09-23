import { ContainerModule } from "inversify";
import { SYSTEM_MAP_SERVICE, SystemMapService } from "./systemMapService";

export const systemMapCoreModule = new ContainerModule(({ bind }) => {
  bind(SYSTEM_MAP_SERVICE).to(SystemMapService).inSingletonScope();
});
