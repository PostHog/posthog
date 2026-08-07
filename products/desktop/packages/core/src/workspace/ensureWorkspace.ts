import type { Workspace, WorkspaceMode } from "@posthog/shared";

export interface CreateWorkspaceRequest {
  taskId: string;
  mainRepoPath: string;
  folderId: string;
  folderPath: string;
  mode: WorkspaceMode;
  branch: string | undefined;
}

export function buildCreateWorkspaceRequest(
  taskId: string,
  repoPath: string,
  mode: WorkspaceMode = "worktree",
  branch?: string | null,
): CreateWorkspaceRequest {
  return {
    taskId,
    mainRepoPath: repoPath,
    folderId: "",
    folderPath: repoPath,
    mode,
    branch: branch ?? undefined,
  };
}

export function selectExistingWorkspace(
  workspaces: Record<string, Workspace> | undefined,
  taskId: string,
): Workspace | null {
  return workspaces?.[taskId] ?? null;
}
