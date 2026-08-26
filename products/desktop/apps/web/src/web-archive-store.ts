import { z } from "zod";
import { createRecordStore } from "./web-local-store";

// Per-device archived-task registry for the web host, backed by localStorage.
//
// On desktop, archiving is a LOCAL operation: it trashes the task's local
// worktree and records the task in a local archive registry — the task still
// exists on the PostHog server. The cloud-only web host has no worktree, so
// archiving is purely "hide this task from my sidebar on this device", which
// this store persists. Shape mirrors the workspace store (web-workspace-store).

const webArchivedTaskSchema = z.object({
  taskId: z.string(),
  archivedAt: z.string(),
  folderId: z.string(),
  mode: z.enum(["worktree", "local", "cloud"]),
  worktreeName: z.string().nullable(),
  branchName: z.string().nullable(),
  checkpointId: z.string().nullable(),
});

export type WebArchivedTask = z.infer<typeof webArchivedTaskSchema>;

const store = createRecordStore(
  "posthog-code:web-archived-tasks",
  webArchivedTaskSchema,
);

export const webArchiveStore = {
  list(): WebArchivedTask[] {
    return Object.values(store.get());
  },

  ids(): string[] {
    return Object.keys(store.get());
  },

  add(taskId: string, archivedAt: string): WebArchivedTask {
    const entry: WebArchivedTask = {
      taskId,
      archivedAt,
      folderId: "",
      mode: "cloud",
      worktreeName: null,
      branchName: null,
      checkpointId: null,
    };
    store.set({ ...store.get(), [taskId]: entry });
    return entry;
  },

  remove(taskId: string): void {
    const current = store.get();
    if (!(taskId in current)) return;
    const { [taskId]: _removed, ...rest } = current;
    store.set(rest);
  },
};
