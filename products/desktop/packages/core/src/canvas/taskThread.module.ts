import { ContainerModule } from "inversify";
import { TASK_THREAD_SERVICE, TaskThreadService } from "./taskThreadService";

export const taskThreadCoreModule = new ContainerModule(({ bind }) => {
  bind(TaskThreadService).toSelf().inSingletonScope();
  bind(TASK_THREAD_SERVICE).toService(TaskThreadService);
});
