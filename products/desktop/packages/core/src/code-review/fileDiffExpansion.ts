import { type FileDiffMetadata, parseDiffFromFile } from "@pierre/diffs";

export function canExpandFileDiff(
  patchFileDiff: FileDiffMetadata,
  repoPath: string | undefined,
  skip: boolean,
): boolean {
  const filePath = patchFileDiff.name ?? patchFileDiff.prevName ?? "";
  return (
    !skip &&
    !!repoPath &&
    !!filePath &&
    patchFileDiff.type !== "deleted" &&
    patchFileDiff.type !== "rename-pure"
  );
}

export function buildExpandedFileDiff(
  patchFileDiff: FileDiffMetadata,
  headContent: string | null | undefined,
  workingContent: string | null | undefined,
): FileDiffMetadata {
  if (headContent === undefined || workingContent === undefined)
    return patchFileDiff;
  const filePath = patchFileDiff.name ?? patchFileDiff.prevName ?? "";
  const prevPath = patchFileDiff.prevName ?? filePath;
  try {
    return parseDiffFromFile(
      { name: prevPath, contents: headContent ?? "" },
      { name: filePath, contents: workingContent ?? "" },
    );
  } catch {
    return patchFileDiff;
  }
}
