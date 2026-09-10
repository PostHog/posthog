export function normalizeRepoKey(key: string): string {
  return key.trim().replace(/\.git$/, "");
}
