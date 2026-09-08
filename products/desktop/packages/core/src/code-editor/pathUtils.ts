/**
 * The part of `absolutePath` below `repoPath`, or `absolutePath` unchanged when
 * it sits outside. The separator has to match too: `/repo-two/a.ts` is not
 * inside `/repo`, and slicing it by prefix length would name a file that does
 * not exist.
 *
 * Windows supplies the two sides with different separators. A worktree root
 * comes from Node `path.join` and holds `\`, while a `file:///C:/…` href
 * decodes to `/`. Both sides are compared as `/` so the boundary still lines
 * up; the returned tail keeps the separators the caller passed in.
 */
export function getRelativePath(
  absolutePath: string,
  repoPath: string | null | undefined,
): string {
  if (!repoPath) return absolutePath;
  const normalizedRepo = repoPath.replaceAll("\\", "/");
  const root = normalizedRepo.endsWith("/")
    ? normalizedRepo.slice(0, -1)
    : normalizedRepo;
  // Same length as `absolutePath`, so `root.length` still indexes into it.
  const candidate = absolutePath.replaceAll("\\", "/");
  if (candidate === root) return "";
  if (!candidate.startsWith(`${root}/`)) return absolutePath;
  return absolutePath.slice(root.length + 1);
}
