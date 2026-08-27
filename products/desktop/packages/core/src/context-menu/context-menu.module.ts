import { ContainerModule } from "inversify";
import { ContextMenuService } from "./context-menu";
import { CONTEXT_MENU_CONTROLLER } from "./identifiers";

export const contextMenuCoreModule = new ContainerModule(({ bind }) => {
  bind(CONTEXT_MENU_CONTROLLER).to(ContextMenuService).inSingletonScope();
});
