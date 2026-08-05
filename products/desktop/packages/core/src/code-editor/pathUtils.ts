// A path counts as inside the repo only when the repo path is followed by a
// separator, so a sibling directory whose name merely starts the same way
// (`/a/project2` against repo `/a/project`) is not taken for repo content. Both
// separators are accepted because this is host-agnostic and runs on Windows.
export function isInsideRepoPath(
  absolutePath: string,
  repoPath: string | null | undefined,
): boolean {
  if (!repoPath) {
    return false;
  }
  const base = stripTrailingSeparator(repoPath);
  if (absolutePath === base) {
    return true;
  }
  const boundary = absolutePath[base.length];
  return (
    absolutePath.startsWith(base) && (boundary === "/" || boundary === "\\")
  );
}

export function getRelativePath(
  absolutePath: string,
  repoPath: string | null | undefined,
): string {
  if (!repoPath || !isInsideRepoPath(absolutePath, repoPath)) {
    return absolutePath;
  }
  return absolutePath.slice(stripTrailingSeparator(repoPath).length + 1);
}

function stripTrailingSeparator(value: string): string {
  return value.replace(/[/\\]+$/, "");
}
