import { ContainerModule } from "inversify";
import { CloudTaskService } from "./cloud-task";
import { CLOUD_TASK_SERVICE } from "./identifiers";

export const cloudTaskModule = new ContainerModule(({ bind }) => {
  bind(CLOUD_TASK_SERVICE).to(CloudTaskService).inSingletonScope();
});
