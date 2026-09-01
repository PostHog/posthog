import { z } from "zod";

// Archived-task domain shape. The canonical runtime boundary validator lives in
// the workspace-server archive service (`archivedTaskSchema`); this mirror is
// the host-agnostic domain type consumed by packages/ui for optimistic cache
// writes, so the UI never imports workspace-server.
export const archivedTaskSchema = z.object({
  taskId: z.string(),
  archivedAt: z.string(),
  folderId: z.string(),
  mode: z.enum(["worktree", "local", "cloud"]),
  worktreeName: z.string().nullable(),
  branchName: z.string().nullable(),
  checkpointId: z.string().nullable(),
  title: z.string().nullable().optional(),
  taskCreatedAt: z.string().nullable().optional(),
  repository: z.string().nullable().optional(),
  recoveryPending: z.boolean().optional(),
});

export type ArchivedTask = z.infer<typeof archivedTaskSchema>;
