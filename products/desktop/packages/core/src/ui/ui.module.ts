import { ContainerModule } from "inversify";
import { UI_SERVICE } from "./identifiers";
import { UIService } from "./ui";

export const uiModule = new ContainerModule(({ bind }) => {
  bind(UI_SERVICE).to(UIService).inSingletonScope();
});
