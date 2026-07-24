import { isAbsolutePath } from "@posthog/shared";

export function resolveTabAbsolutePath(
  relativePath: string,
  repoPath: string,
): string {
  if (isAbsolutePath(relativePath)) {
    return relativePath;
  }
  return repoPath ? `${repoPath}/${relativePath}` : relativePath;
}
