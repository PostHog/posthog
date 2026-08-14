export const UNARCHIVE_SERVICE = Symbol.for("posthog.core.unarchiveService");
export const ARCHIVED_TASKS_CONTROLLER = Symbol.for(
  "posthog.core.archivedTasksController",
);
export const ARCHIVE_CLIENT = Symbol.for("posthog.core.archiveClient");

export type ArchivedTaskContextMenuAction = "restore" | "delete";

export interface ArchiveClient {
  unarchive(input: {
    taskId: string;
    recreateBranch?: boolean;
  }): Promise<unknown>;
  delete(input: { taskId: string }): Promise<unknown>;
  showArchivedTaskContextMenu(input: { taskTitle: string }): Promise<{
    action: { type: ArchivedTaskContextMenuAction } | null;
  }>;
}
