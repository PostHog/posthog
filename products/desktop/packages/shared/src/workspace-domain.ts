import { z } from "zod";

// Workspace projection/boundary schemas. Shared between the workspace-server
// host service (which produces them) and the renderer/UI (which renders them).
// Note: "root" is deprecated, migrated to "local" on read.
export const workspaceModeSchema = z
  .enum(["worktree", "local", "cloud", "root"])
  .transform((val) => (val === "root" ? "local" : val));

export const worktreeInfoSchema = z.object({
  worktreePath: z.string(),
  worktreeName: z.string(),
  branchName: z.string().nullable(),
  baseBranch: z.string(),
  createdAt: z.string(),
  output: z.string().optional(),
});

export const workspaceInfoSchema = z.object({
  taskId: z.string(),
  mode: workspaceModeSchema,
  worktree: worktreeInfoSchema.nullable(),
  branchName: z.string().nullable(),
  linkedBranch: z.string().nullable(),
});

export const workspaceSchema = z.object({
  taskId: z.string(),
  folderId: z.string(),
  folderPath: z.string(),
  mode: workspaceModeSchema,
  worktreePath: z.string().nullable(),
  worktreeName: z.string().nullable(),
  branchName: z.string().nullable(),
  baseBranch: z.string().nullable(),
  linkedBranch: z.string().nullable(),
  createdAt: z.string(),
  /**
   * Synthetic workspace for a repo-less channel task: its folderPath is a
   * scratch dir, not a registered folder. Marks it so callers (e.g. the
   * navigation task binder) don't try to register it as a folder or git-init it.
   */
  isScratch: z.boolean().optional(),
});

export type WorktreeInfo = z.infer<typeof worktreeInfoSchema>;
export type WorkspaceInfo = z.infer<typeof workspaceInfoSchema>;
export type Workspace = z.infer<typeof workspaceSchema>;
