import type { Workspace } from "@posthog/shared";

export interface EnableFocusParams {
  mainRepoPath: string;
  worktreePath: string;
  branch: string;
}

export function canFocusWorkspace(workspace: Workspace | null): boolean {
  return (
    !!workspace &&
    workspace.mode === "worktree" &&
    !!workspace.branchName &&
    !!workspace.worktreePath
  );
}

export function focusTerminalKey(taskId: string, branch: string): string {
  return `focus-terminal-${taskId}-${branch}`;
}

export function buildEnableFocusParams(
  workspace: Workspace | null,
): EnableFocusParams | null {
  if (!canFocusWorkspace(workspace) || !workspace) {
    return null;
  }
  return {
    mainRepoPath: workspace.folderPath,
    // biome-ignore lint/style/noNonNullAssertion: guarded by canFocusWorkspace
    worktreePath: workspace.worktreePath!,
    // biome-ignore lint/style/noNonNullAssertion: guarded by canFocusWorkspace
    branch: workspace.branchName!,
  };
}
