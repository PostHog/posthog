import { ContainerModule } from "inversify";
import { ArchivedTasksController } from "./archivedTasksController";
import { ARCHIVED_TASKS_CONTROLLER, UNARCHIVE_SERVICE } from "./identifiers";
import { UnarchiveService } from "./unarchiveService";

export const archiveModule = new ContainerModule(({ bind }) => {
  bind(UNARCHIVE_SERVICE).to(UnarchiveService).inSingletonScope();
  bind(ARCHIVED_TASKS_CONTROLLER)
    .to(ArchivedTasksController)
    .inSingletonScope();
});
