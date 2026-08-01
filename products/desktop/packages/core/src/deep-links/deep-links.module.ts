import { ContainerModule } from "inversify";
import { NEW_TASK_LINK_RESOLVER } from "./identifiers";
import { NewTaskLinkResolver } from "./newTaskLinkResolver";

export const deepLinksCoreModule = new ContainerModule(({ bind }) => {
  bind(NEW_TASK_LINK_RESOLVER).to(NewTaskLinkResolver).inSingletonScope();
});
