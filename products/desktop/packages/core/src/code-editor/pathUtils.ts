/**
 * The part of `absolutePath` below `repoPath`, or `absolutePath` unchanged when
 * it sits outside. The separator has to match too: `/repo-two/a.ts` is not
 * inside `/repo`, and slicing it by prefix length would name a file that does
 * not exist.
 */
export function getRelativePath(
  absolutePath: string,
  repoPath: string | null | undefined,
): string {
  if (!repoPath) return absolutePath;
  const root = repoPath.endsWith("/") ? repoPath.slice(0, -1) : repoPath;
  if (absolutePath === root) return "";
  if (!absolutePath.startsWith(`${root}/`)) return absolutePath;
  return absolutePath.slice(root.length + 1);
}
