import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { inject, injectable } from "inversify";
import {
  type ITaskDeletionHost,
  type ITaskDeletionWorkspaceClient,
  TASK_DELETION_HOST,
  TASK_DELETION_SERVICE,
  TASK_DELETION_WORKSPACE_CLIENT,
} from "./identifiers";
import {
  shouldNavigateAwayFromDeletedTask,
  shouldUnfocusBeforeDelete,
} from "./taskDelete";

export { TASK_DELETION_SERVICE };

export interface TaskCloudDeleteClient {
  deleteTask(taskId: string): Promise<unknown>;
}

export interface ConfirmAndDeleteParams {
  taskId: string;
  taskTitle: string;
  hasWorktree: boolean;
}

@injectable()
export class TaskDeletionService {
  constructor(
    @inject(TASK_DELETION_WORKSPACE_CLIENT)
    private readonly workspace: ITaskDeletionWorkspaceClient,
    @inject(TASK_DELETION_HOST)
    private readonly host: ITaskDeletionHost,
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    this.logger = rootLogger.scope("tasks");
  }

  private readonly logger: ScopedLogger;

  async deleteTask(
    client: TaskCloudDeleteClient,
    taskId: string,
  ): Promise<unknown> {
    const all = await this.workspace.getAll();
    const workspace = all[taskId] ?? null;

    if (workspace) {
      if (shouldUnfocusBeforeDelete(this.host.getSession(), workspace)) {
        this.logger.info("Unfocusing workspace before deletion");
        await this.host.disableFocus();
      }

      if (workspace.folderPath) {
        try {
          await this.workspace.delete({
            taskId,
            mainRepoPath: workspace.folderPath,
          });
        } catch (error) {
          this.logger.error("Failed to delete workspace:", error);
        }
      }
    }

    return client.deleteTask(taskId);
  }

  async confirmAndDelete(
    params: ConfirmAndDeleteParams,
    runDelete: (taskId: string) => Promise<unknown>,
  ): Promise<boolean> {
    const { taskId, taskTitle, hasWorktree } = params;

    const result = await this.host.confirmDeleteTask({
      taskTitle,
      hasWorktree,
    });
    if (!result.confirmed) {
      return false;
    }

    if (shouldNavigateAwayFromDeletedTask(this.host.getCurrentView(), taskId)) {
      this.host.navigateToTaskInput();
    }

    await this.host.unpin(taskId);

    await runDelete(taskId);

    return true;
  }
}
