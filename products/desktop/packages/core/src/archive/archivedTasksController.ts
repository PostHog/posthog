import { inject, injectable } from "inversify";
import { ARCHIVED_TASKS_CONTROLLER, UNARCHIVE_SERVICE } from "./identifiers";
import type { UnarchiveService } from "./unarchiveService";

export { ARCHIVED_TASKS_CONTROLLER };

export type RestoreOutcome =
  | { kind: "restored"; navigateToTaskId: string | null }
  | { kind: "branch-not-found"; taskId: string; branchName: string }
  | { kind: "error"; message: string };

export type DeleteOutcome =
  | { kind: "deleted" }
  | { kind: "error"; message: string };

export type ContextMenuOutcome =
  | { kind: "noop" }
  | { kind: "menu-error"; message: string }
  | { kind: "restore"; outcome: RestoreOutcome }
  | { kind: "delete"; outcome: DeleteOutcome };

@injectable()
export class ArchivedTasksController {
  constructor(
    @inject(UNARCHIVE_SERVICE)
    private readonly unarchive: UnarchiveService,
  ) {}

  async restore(
    taskId: string,
    hasTask: boolean,
    options?: { recreateBranch?: boolean },
  ): Promise<RestoreOutcome> {
    const result = await this.unarchive.unarchiveTask(taskId, options);
    if (result.ok) {
      return { kind: "restored", navigateToTaskId: hasTask ? taskId : null };
    }
    if (result.kind === "branch-not-found") {
      return {
        kind: "branch-not-found",
        taskId,
        branchName: result.branchName,
      };
    }
    return { kind: "error", message: result.message };
  }

  async remove(taskId: string): Promise<DeleteOutcome> {
    const result = await this.unarchive.deleteArchivedTask(taskId);
    if (result.ok) {
      return { kind: "deleted" };
    }
    return { kind: "error", message: result.message };
  }

  async runContextMenuAction(
    taskId: string,
    taskTitle: string,
    hasTask: boolean,
  ): Promise<ContextMenuOutcome> {
    const result = await this.unarchive.requestContextMenuAction(taskTitle);
    if ("error" in result) {
      return { kind: "menu-error", message: result.error };
    }
    if (result.action === "restore") {
      return { kind: "restore", outcome: await this.restore(taskId, hasTask) };
    }
    if (result.action === "delete") {
      return { kind: "delete", outcome: await this.remove(taskId) };
    }
    return { kind: "noop" };
  }
}
