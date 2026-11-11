import { ContainerModule } from "inversify";
import { TASK_SERVICE, WORKSPACE_SETUP_SAGA } from "./identifiers";
import { TaskService } from "./taskService";
import { WARM_TASK_SERVICE, WarmTaskService } from "./warmTaskService";
import { WorkspaceSetupSaga } from "./workspaceSetupSaga";

export const taskDetailModule = new ContainerModule(({ bind }) => {
  bind(WARM_TASK_SERVICE).to(WarmTaskService).inSingletonScope();
  bind(TASK_SERVICE).to(TaskService).inSingletonScope();
  bind(WORKSPACE_SETUP_SAGA).to(WorkspaceSetupSaga).inSingletonScope();
});
