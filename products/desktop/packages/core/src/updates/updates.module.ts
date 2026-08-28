import { ContainerModule } from "inversify";
import { UPDATES_SERVICE } from "./identifiers";
import { UpdatesService } from "./updates";

export const updatesCoreModule = new ContainerModule(({ bind }) => {
  bind(UPDATES_SERVICE).to(UpdatesService).inSingletonScope();
});
