import type { parsePatchFiles } from "@pierre/diffs";
import { contentHash } from "@posthog/core/code-review/contentHash";
import type { PrCommentThread } from "@posthog/core/code-review/types";
import { isBinaryFile } from "@posthog/shared";
import type { ChangedFile } from "@posthog/shared/domain-types";
import { memo, useCallback, useMemo } from "react";
import { useInView } from "../../../primitives/hooks/useInView";
import { REVIEW_PREFETCH_ROOT_MARGIN } from "../constants";
import { useReadRepoFileBounded } from "../hooks/useReadRepoFileBounded";
import {
  DeferredDiffPlaceholder,
  DiffFileHeader,
  FileHeaderRow,
  splitFilePath,
} from "../reviewShellParts";
import type { DiffOptions } from "../types";
import { BinaryFileDiff } from "./BinaryFileDiff";
import { InteractiveFileDiff } from "./InteractiveFileDiff";
import { PatchedFileDiff } from "./PatchedFileDiff";

interface PatchRowProps {
  itemKey: string;
  filePath: string;
  fileDiff: ReturnType<typeof parsePatchFiles>[number]["files"][number];
  repoPath: string;
  taskId: string;
  diffOptions: DiffOptions;
  collapsed: boolean;
  skipExpansion: boolean;
  toggleFile: (key: string) => void;
  openFile: (taskId: string, path: string, preview: boolean) => void;
  onDiscardFile?: (key: string) => void;
  onStageFile?: (key: string) => void;
  staged?: boolean;
  prUrl: string | null;
  commentThreads?: Map<number, PrCommentThread>;
}

export const PatchRow = memo(function PatchRow({
  itemKey,
  filePath,
  fileDiff,
  repoPath,
  taskId,
  diffOptions,
  collapsed,
  skipExpansion,
  toggleFile,
  openFile,
  onDiscardFile,
  onStageFile,
  staged,
  prUrl,
  commentThreads,
}: PatchRowProps) {
  const onToggle = useCallback(
    () => toggleFile(itemKey),
    [toggleFile, itemKey],
  );
  const onOpenFile = useCallback(
    () => openFile(taskId, `${repoPath}/${filePath}`, false),
    [openFile, taskId, repoPath, filePath],
  );
  const onDiscard = useMemo(
    () => (onDiscardFile ? () => onDiscardFile(itemKey) : undefined),
    [onDiscardFile, itemKey],
  );
  const onStage = useMemo(
    () => (onStageFile ? () => onStageFile(itemKey) : undefined),
    [onStageFile, itemKey],
  );
  const options = useMemo(
    () => ({ ...diffOptions, collapsed }),
    [diffOptions, collapsed],
  );
  const renderHeader = useCallback(
    (fd: typeof fileDiff) => (
      <DiffFileHeader
        fileDiff={fd}
        collapsed={collapsed}
        onToggle={onToggle}
        onOpenFile={onOpenFile}
        onDiscard={onDiscard}
        onStage={onStage}
        staged={staged}
        viewedKey={itemKey}
      />
    ),
    [collapsed, onToggle, onOpenFile, onDiscard, onStage, staged, itemKey],
  );

  // Binary files (images, video, archives, …) have no meaningful textual diff;
  // preview the working-tree file or show a clean placeholder instead of the
  // "Binary files differ" sentinel the diff renderer would otherwise display.
  if (isBinaryFile(filePath)) {
    return (
      <BinaryFileDiff
        filePath={filePath}
        absolutePath={`${repoPath}/${filePath}`}
        collapsed={collapsed}
        onToggle={onToggle}
        onOpenFile={onOpenFile}
      />
    );
  }

  return (
    <InteractiveFileDiff
      fileDiff={fileDiff}
      repoPath={repoPath}
      skipExpansion={skipExpansion}
      options={options}
      taskId={taskId}
      prUrl={prUrl}
      commentThreads={commentThreads}
      renderCustomHeader={renderHeader}
    />
  );
});

interface UntrackedRowProps {
  itemKey: string;
  file: ChangedFile;
  repoPath: string;
  taskId: string;
  diffOptions: DiffOptions;
  collapsed: boolean;
  toggleFile: (key: string) => void;
  onDiscardFile?: (key: string) => void;
  onStageFile?: (key: string) => void;
}

export const UntrackedRow = memo(function UntrackedRow({
  itemKey,
  file,
  repoPath,
  taskId,
  diffOptions,
  collapsed,
  toggleFile,
  onDiscardFile,
  onStageFile,
}: UntrackedRowProps) {
  const onToggle = useCallback(
    () => toggleFile(itemKey),
    [toggleFile, itemKey],
  );
  const onDiscard = useMemo(
    () => (onDiscardFile ? () => onDiscardFile(itemKey) : undefined),
    [onDiscardFile, itemKey],
  );
  const onStage = useMemo(
    () => (onStageFile ? () => onStageFile(itemKey) : undefined),
    [onStageFile, itemKey],
  );

  // A new binary file would otherwise be read as text and fed to the diff
  // renderer; preview it (image/video) or show a clean placeholder instead.
  if (isBinaryFile(file.path)) {
    return (
      <BinaryFileDiff
        filePath={file.path}
        absolutePath={`${repoPath}/${file.path}`}
        collapsed={collapsed}
        onToggle={onToggle}
      />
    );
  }

  return (
    <UntrackedFileDiff
      file={file}
      repoPath={repoPath}
      options={diffOptions}
      collapsed={collapsed}
      onToggle={onToggle}
      onDiscard={onDiscard}
      onStage={onStage}
      taskId={taskId}
      viewedKey={itemKey}
    />
  );
});

interface RemoteRowProps {
  file: ChangedFile;
  taskId: string;
  prUrl?: string | null;
  options: DiffOptions;
  collapsed: boolean;
  toggleFile: (path: string) => void;
  commentThreads?: Map<number, PrCommentThread>;
  externalUrl?: string;
}

export const RemoteRow = memo(function RemoteRow({
  file,
  taskId,
  prUrl,
  options,
  collapsed,
  toggleFile,
  commentThreads,
  externalUrl,
}: RemoteRowProps) {
  const onToggle = useCallback(
    () => toggleFile(file.path),
    [toggleFile, file.path],
  );
  return (
    <PatchedFileDiff
      file={file}
      taskId={taskId}
      prUrl={prUrl}
      options={options}
      collapsed={collapsed}
      onToggle={onToggle}
      commentThreads={commentThreads}
      externalUrl={externalUrl}
      viewedKey={file.path}
    />
  );
});

function UntrackedFileDiff({
  file,
  repoPath,
  taskId,
  options,
  collapsed,
  onToggle,
  onDiscard,
  onStage,
  viewedKey,
}: {
  file: ChangedFile;
  repoPath: string;
  taskId: string;
  options: DiffOptions;
  collapsed: boolean;
  onToggle: () => void;
  onDiscard?: () => void;
  onStage?: () => void;
  viewedKey?: string;
}) {
  const [containerRef, inView] = useInView<HTMLDivElement>({
    rootMargin: REVIEW_PREFETCH_ROOT_MARGIN,
    once: true,
  });
  const { data: result } = useReadRepoFileBounded(
    repoPath,
    file.path,
    !collapsed && inView,
  );

  const content = result?.kind === "content" ? result.content : null;

  const oldFile = useMemo(
    () => ({
      name: file.path,
      contents: "",
      cacheKey: `untracked-old:${file.path}`,
    }),
    [file.path],
  );
  const newFile = useMemo(
    () => ({
      name: file.path,
      contents: content ?? "",
      cacheKey: content
        ? `untracked-new:${file.path}:${contentHash(content)}`
        : undefined,
    }),
    [file.path, content],
  );

  if (!collapsed && inView && result?.kind === "too-large") {
    return (
      <DeferredDiffPlaceholder
        filePath={file.path}
        linesAdded={file.linesAdded ?? 0}
        linesRemoved={0}
        reason="line-limit"
        collapsed={collapsed}
        onToggle={onToggle}
        viewedKey={viewedKey}
      />
    );
  }

  const hasContent = result?.kind === "content";
  const { dirPath, fileName } = splitFilePath(file.path);

  return (
    <div ref={containerRef}>
      {hasContent ? (
        <InteractiveFileDiff
          oldFile={oldFile}
          newFile={newFile}
          options={{ ...options, collapsed }}
          taskId={taskId}
          renderCustomHeader={(fd) => (
            <DiffFileHeader
              fileDiff={fd}
              collapsed={collapsed}
              onToggle={onToggle}
              onDiscard={onDiscard}
              onStage={onStage}
              staged={false}
              viewedKey={viewedKey}
            />
          )}
        />
      ) : (
        <FileHeaderRow
          dirPath={dirPath}
          fileName={fileName}
          additions={file.linesAdded ?? 0}
          deletions={0}
          collapsed={collapsed}
          onToggle={onToggle}
          viewedKey={viewedKey}
        />
      )}
    </div>
  );
}
