import type { FileDiffMetadata } from "@pierre/diffs";

export type DeferredReason = "line-limit" | "unavailable" | "binary";

export function splitFilePath(fullPath: string): {
  dirPath: string;
  fileName: string;
} {
  const lastSlash = fullPath.lastIndexOf("/");
  return {
    dirPath: lastSlash >= 0 ? fullPath.slice(0, lastSlash + 1) : "",
    fileName: lastSlash >= 0 ? fullPath.slice(lastSlash + 1) : fullPath,
  };
}

export function sumHunkStats(hunks: FileDiffMetadata["hunks"]): {
  additions: number;
  deletions: number;
} {
  let additions = 0;
  let deletions = 0;
  for (const hunk of hunks) {
    additions += hunk.additionLines;
    deletions += hunk.deletionLines;
  }
  return { additions, deletions };
}

export function buildItemIndex(
  items: { scrollKey?: string }[],
): Map<string, number> {
  const index = new Map<string, number>();
  for (let i = 0; i < items.length; i++) {
    const key = items[i].scrollKey;
    if (key) index.set(key, i);
  }
  return index;
}

export function getDeferredMessage(reason: DeferredReason): string {
  switch (reason) {
    case "line-limit":
      return "File exceeds the 5,000-line review limit.";
    case "unavailable":
      return "Unable to load diff.";
    case "binary":
      return "Binary file not shown.";
  }
}
