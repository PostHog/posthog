import type { Workspace } from "@posthog/shared";

export function resolveLocalRepoPath(
  workspace: Workspace | null,
  isFocused: boolean,
): string | undefined {
  if (!workspace) {
    return undefined;
  }
  return isFocused
    ? workspace.folderPath
    : (workspace.worktreePath ?? workspace.folderPath);
}
