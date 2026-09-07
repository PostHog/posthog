interface RepoPathCandidate {
  worktreePath?: string | null;
  folderPath?: string | null;
}

export function resolveWorkspaceForRepoPath<T extends RepoPathCandidate>(
  workspaces: Record<string, T | null | undefined>,
  repoPath: string | undefined,
): T | null {
  if (!repoPath) return null;

  return (
    Object.values(workspaces).find(
      (ws): ws is T =>
        !!ws && (ws.worktreePath === repoPath || ws.folderPath === repoPath),
    ) ?? null
  );
}
