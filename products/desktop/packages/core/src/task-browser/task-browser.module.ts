import { ContainerModule } from "inversify";
import { TASK_BROWSER_SERVICE } from "./identifiers";
import { TaskBrowserService } from "./taskBrowserService";

export const taskBrowserModule = new ContainerModule(({ bind }) => {
  bind(TASK_BROWSER_SERVICE).to(TaskBrowserService).inSingletonScope();
});
