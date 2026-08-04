import { type Workspace, workspaceSchema } from "@posthog/shared";
import { createRecordStore } from "./web-local-store";

// Per-device cloud-workspace registry for the web host, backed by localStorage.
//
// Desktop persists a workspace row (SQLite) when a cloud task is created, so
// workspace.getAll returns it and the sidebar — whose default view derives its
// task list from the workspace map (computeSummaryIds) — shows the task. The
// browser has no such backend, so this is the scaled-down equivalent: create
// adds a cloud entry, getAll returns the map, delete removes it, and the map
// survives reloads via localStorage. Scope matches desktop: cloud tasks created
// in THIS browser appear in the sidebar.

const store = createRecordStore(
  "posthog-code:web-cloud-workspaces",
  workspaceSchema,
);

export const webWorkspaceStore = {
  getAll(): Record<string, Workspace> {
    return store.get();
  },

  /** Register (or overwrite) a cloud workspace for a task. */
  addCloud(taskId: string, branch: string | null, createdAt: string): void {
    store.set({
      ...store.get(),
      [taskId]: {
        taskId,
        folderId: "",
        folderPath: "",
        mode: "cloud",
        worktreePath: null,
        worktreeName: null,
        branchName: null,
        baseBranch: branch,
        linkedBranch: null,
        createdAt,
      },
    });
  },

  remove(taskId: string): void {
    const current = store.get();
    if (!(taskId in current)) return;
    const { [taskId]: _removed, ...rest } = current;
    store.set(rest);
  },
};
