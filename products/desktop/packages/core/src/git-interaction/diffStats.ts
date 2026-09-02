import { isBinaryFile } from "@posthog/shared";
import type { ChangedFile } from "@posthog/shared/domain-types";

export interface DiffStats {
  filesChanged: number;
  linesAdded: number;
  linesRemoved: number;
}

export function computeDiffStats(files: ChangedFile[]): DiffStats {
  let linesAdded = 0;
  let linesRemoved = 0;
  const uniquePaths = new Set<string>();
  for (const file of files) {
    uniquePaths.add(file.path);
    if (isBinaryFile(file.path)) continue;
    linesAdded += file.linesAdded ?? 0;
    linesRemoved += file.linesRemoved ?? 0;
  }
  return { filesChanged: uniquePaths.size, linesAdded, linesRemoved };
}

export function formatFileCountLabel(
  stagedOnly: boolean,
  stagedFileCount: number,
  totalFileCount: number,
): string {
  if (stagedOnly) {
    return `${stagedFileCount} staged file${stagedFileCount === 1 ? "" : "s"}`;
  }
  return `${totalFileCount} file${totalFileCount === 1 ? "" : "s"}`;
}

export function partitionByStaged(files: ChangedFile[]): {
  stagedFiles: ChangedFile[];
  unstagedFiles: ChangedFile[];
} {
  const stagedFiles: ChangedFile[] = [];
  const unstagedFiles: ChangedFile[] = [];
  for (const f of files) {
    if (f.staged) stagedFiles.push(f);
    else unstagedFiles.push(f);
  }
  return { stagedFiles, unstagedFiles };
}
