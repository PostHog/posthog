export function getRelativePath(
  absolutePath: string,
  repoPath: string | null | undefined,
): string {
  if (!repoPath || !absolutePath.startsWith(repoPath)) {
    return absolutePath;
  }
  return absolutePath.slice(repoPath.length + 1);
}
