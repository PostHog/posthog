import { ContainerModule } from "inversify";
import { TASK_SERVICE, WORKSPACE_SETUP_SAGA } from "./identifiers";
import { TaskService } from "./taskService";
import { WorkspaceSetupSaga } from "./workspaceSetupSaga";

export const taskDetailModule = new ContainerModule(({ bind }) => {
  bind(TASK_SERVICE).to(TaskService).inSingletonScope();
  bind(WORKSPACE_SETUP_SAGA).to(WorkspaceSetupSaga).inSingletonScope();
});
