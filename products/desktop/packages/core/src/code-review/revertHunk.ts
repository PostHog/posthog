import { diffAcceptRejectHunk, parseDiffFromFile } from "@pierre/diffs";

export function revertHunkContent(
  filePath: string,
  originalContent: string,
  modifiedContent: string,
  hunkIndex: number,
): string {
  const fullDiff = parseDiffFromFile(
    { name: filePath, contents: originalContent },
    { name: filePath, contents: modifiedContent },
  );
  const reverted = diffAcceptRejectHunk(fullDiff, hunkIndex, "reject");
  return reverted.additionLines.join("");
}
