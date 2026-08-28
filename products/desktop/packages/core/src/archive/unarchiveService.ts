import { inject, injectable } from "inversify";
import {
  ARCHIVE_CLIENT,
  type ArchiveClient,
  type ArchivedTaskContextMenuAction,
  UNARCHIVE_SERVICE,
} from "./identifiers";
import { parseUnarchiveError } from "./parseUnarchiveError";

export { UNARCHIVE_SERVICE };

export type UnarchiveResult =
  | { ok: true }
  | { ok: false; kind: "branch-not-found"; branchName: string }
  | { ok: false; kind: "other"; message: string };

export type DeleteArchivedTaskResult =
  | { ok: true }
  | { ok: false; message: string };

export type ContextMenuActionResult =
  | { action: ArchivedTaskContextMenuAction | null }
  | { error: string };

@injectable()
export class UnarchiveService {
  constructor(
    @inject(ARCHIVE_CLIENT) private readonly archive: ArchiveClient,
  ) {}

  async unarchiveTask(
    taskId: string,
    options?: { recreateBranch?: boolean },
  ): Promise<UnarchiveResult> {
    try {
      await this.archive.unarchive({
        taskId,
        recreateBranch: options?.recreateBranch,
      });
      return { ok: true };
    } catch (error) {
      const parsed = parseUnarchiveError(error);
      if (parsed.kind === "branch-not-found") {
        return {
          ok: false,
          kind: "branch-not-found",
          branchName: parsed.branchName,
        };
      }
      return { ok: false, kind: "other", message: parsed.message };
    }
  }

  async deleteArchivedTask(taskId: string): Promise<DeleteArchivedTaskResult> {
    try {
      await this.archive.delete({ taskId });
      return { ok: true };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { ok: false, message };
    }
  }

  async requestContextMenuAction(
    taskTitle: string,
  ): Promise<ContextMenuActionResult> {
    try {
      const result = await this.archive.showArchivedTaskContextMenu({
        taskTitle,
      });
      return { action: result.action?.type ?? null };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return { error: message };
    }
  }
}
