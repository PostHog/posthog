import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import type { Workspace, WorkspaceMode } from "@posthog/shared";
import { inject, injectable } from "inversify";

export { WORKSPACE_SETUP_SAGA } from "./identifiers";

export interface WorkspaceSetupExecutor {
  addFolder(path: string): Promise<unknown>;
  ensureWorkspace(
    taskId: string,
    path: string,
    mode: WorkspaceMode,
  ): Promise<Workspace | null>;
}

export type WorkspaceSetupResult =
  | { success: true }
  | { success: false; error: string };

@injectable()
export class WorkspaceSetupSaga {
  private readonly log: ReturnType<RootLogger["scope"]>;

  constructor(
    @inject(ROOT_LOGGER)
    rootLogger: RootLogger,
  ) {
    this.log = rootLogger.scope("task-service");
  }

  public async setupWorkspace(
    executor: WorkspaceSetupExecutor,
    taskId: string,
    path: string,
  ): Promise<WorkspaceSetupResult> {
    try {
      await executor.addFolder(path);
      await executor.ensureWorkspace(taskId, path, "worktree");
      this.log.info("Workspace setup complete", { taskId, path });
      return { success: true };
    } catch (error) {
      this.log.error("Failed to set up workspace", { taskId, path, error });
      const message = error instanceof Error ? error.message : String(error);
      return { success: false, error: message };
    }
  }
}
