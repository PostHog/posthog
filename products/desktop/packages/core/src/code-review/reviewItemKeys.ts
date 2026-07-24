export function computeSkipExpansion(
  staged: boolean,
  filePath: string,
  alsoStagedPaths: Set<string> | undefined,
): boolean {
  return staged || (alsoStagedPaths?.has(filePath) ?? false);
}

export function buildGithubFileUrl(
  prUrl: string | null | undefined,
  filePath: string,
): string | undefined {
  if (!prUrl) return undefined;
  return `${prUrl}/files#diff-${filePath.replaceAll("/", "-")}`;
}
