export interface ToolCallFileDiff {
  oldText: string | null;
  newText: string | null;
}

export function buildToolCallFallbacks(
  hasRemoteFiles: boolean,
  reviewFilePaths: string[],
  extractFileDiff: (filePath: string) => ToolCallFileDiff | undefined,
): Map<string, ToolCallFileDiff> | undefined {
  if (hasRemoteFiles) return undefined;
  const diffs = new Map<string, ToolCallFileDiff>();
  for (const filePath of reviewFilePaths) {
    const diff = extractFileDiff(filePath);
    if (diff) diffs.set(filePath, diff);
  }
  return diffs;
}
