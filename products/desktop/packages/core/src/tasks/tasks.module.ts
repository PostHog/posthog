import { ContainerModule } from "inversify";
import { TASK_DELETION_SERVICE } from "./identifiers";
import { TaskDeletionService } from "./taskDeletionService";

export const tasksModule = new ContainerModule(({ bind }) => {
  bind(TASK_DELETION_SERVICE).to(TaskDeletionService).inSingletonScope();
});
