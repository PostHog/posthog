import { type FileDiffMetadata, processFile } from "@pierre/diffs";
import type { PrCommentThread } from "@posthog/core/code-review/types";
import { isBinaryFile } from "@posthog/shared";
import type { ChangedFile } from "@posthog/shared/domain-types";
import { type ReactNode, useMemo } from "react";
import { DeferredDiffPlaceholder, DiffFileHeader } from "../reviewShellParts";
import type { DiffOptions } from "../types";
import { InteractiveFileDiff } from "./InteractiveFileDiff";

interface PatchedFileDiffProps {
  file: ChangedFile;
  taskId: string;
  options: DiffOptions;
  collapsed: boolean;
  onToggle: () => void;
  fallback?: { oldText: string | null; newText: string | null } | null;
  externalUrl?: string;
  prUrl?: string | null;
  commentThreads?: Map<number, PrCommentThread>;
  viewedKey?: string;
  /** Extra controls in the file header row (e.g. a "Viewed" toggle). */
  headerTrailing?: ReactNode;
}

export function PatchedFileDiff({
  file,
  taskId,
  options,
  collapsed,
  onToggle,
  fallback,
  externalUrl,
  prUrl,
  commentThreads,
  viewedKey,
  headerTrailing,
}: PatchedFileDiffProps) {
  const fileDiff = useMemo((): FileDiffMetadata | undefined => {
    if (!file.patch) return undefined;
    return processFile(file.patch, { isGitDiff: true });
  }, [file.patch]);

  const diffSourceProps = useMemo(() => {
    if (fileDiff) return { fileDiff };
    if (fallback) {
      const name = file.path.split("/").pop() || file.path;
      return {
        oldFile: { name, contents: fallback.oldText ?? "" },
        newFile: { name, contents: fallback.newText ?? "" },
      };
    }
    return null;
  }, [fileDiff, fallback, file.path]);
  const commentCount = countPrCommentsForFile(commentThreads, file);

  // Branch/PR diffs have no reliable local working-tree file to preview (the
  // checkout may be on a different ref, and GitHub omits binary patches), so
  // show a clean placeholder instead of letting the binary sentinel render.
  if (isBinaryFile(file.path)) {
    return (
      <DeferredDiffPlaceholder
        filePath={file.path}
        linesAdded={file.linesAdded ?? 0}
        linesRemoved={file.linesRemoved ?? 0}
        reason="binary"
        collapsed={collapsed}
        onToggle={onToggle}
        externalUrl={externalUrl}
        viewedKey={viewedKey}
        commentCount={commentCount}
        headerTrailing={headerTrailing}
      />
    );
  }

  if (!diffSourceProps) {
    return (
      <DeferredDiffPlaceholder
        filePath={file.path}
        linesAdded={file.linesAdded ?? 0}
        linesRemoved={file.linesRemoved ?? 0}
        reason="unavailable"
        collapsed={collapsed}
        onToggle={onToggle}
        externalUrl={externalUrl}
        viewedKey={viewedKey}
        commentCount={commentCount}
        headerTrailing={headerTrailing}
      />
    );
  }

  return (
    <InteractiveFileDiff
      {...diffSourceProps}
      options={{ ...options, collapsed }}
      taskId={taskId}
      prUrl={prUrl}
      commentThreads={commentThreads}
      renderCustomHeader={(fd) => (
        <DiffFileHeader
          fileDiff={fd}
          collapsed={collapsed}
          onToggle={onToggle}
          viewedKey={viewedKey}
          commentCount={commentCount}
          trailing={headerTrailing}
        />
      )}
    />
  );
}

function countPrCommentsForFile(
  threads: Map<number, PrCommentThread> | undefined,
  file: Pick<ChangedFile, "path" | "originalPath">,
): number {
  let count = 0;
  for (const thread of threads?.values() ?? []) {
    if (
      thread.filePath === file.path ||
      (file.originalPath != null && thread.filePath === file.originalPath)
    ) {
      count += thread.comments.length;
    }
  }
  return count;
}
