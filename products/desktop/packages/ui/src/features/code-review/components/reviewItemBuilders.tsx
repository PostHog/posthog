import type { parsePatchFiles } from "@pierre/diffs";
import { contentHash } from "@posthog/core/code-review/contentHash";
import {
  buildGithubFileUrl,
  computeSkipExpansion,
} from "@posthog/core/code-review/reviewItemKeys";
import type { PrCommentThread } from "@posthog/core/code-review/types";
import type { ChangedFile } from "@posthog/shared/domain-types";
import { makeFileKey } from "../../git-interaction/utils/fileKey";
import type { ReviewListItem } from "../commentFileFilter";
import type { DiffOptions } from "../types";
import { PatchRow, RemoteRow, UntrackedRow } from "./ReviewRows";

export function changedFileSignature(file: ChangedFile): string | null {
  if (file.patch) return contentHash(file.patch);
  if (file.sha) return `${file.status}:${file.sha}`;
  return null;
}

export function patchFileSignature(
  fileDiff: ReturnType<typeof parsePatchFiles>[number]["files"][number],
): string {
  // Prefer the git blob object ids from the patch `index` line: they identify
  // file content directly and are unaffected by the hide-whitespace toggle
  // (which re-fetches a different diff that would otherwise change a
  // hunk-derived signature). Fall back to hunk geometry when absent.
  return fileDiff.newObjectId || fileDiff.prevObjectId
    ? `${fileDiff.prevObjectId ?? ""}:${fileDiff.newObjectId ?? ""}`
    : contentHash(JSON.stringify(fileDiff.hunks ?? []));
}

interface BuildPatchReviewItemsArgs {
  files: ReturnType<typeof parsePatchFiles>[number]["files"];
  staged?: boolean;
  alsoStagedPaths?: Set<string>;
  repoPath: string;
  taskId: string;
  diffOptions: DiffOptions;
  collapsedFiles: Set<string>;
  toggleFile: (key: string) => void;
  openFile: (taskId: string, path: string, preview: boolean) => void;
  onDiscardFile?: (key: string) => void;
  onStageFile?: (key: string) => void;
  prUrl: string | null;
  commentThreads?: Map<number, PrCommentThread>;
}

export function buildPatchReviewItems({
  files,
  staged = false,
  alsoStagedPaths,
  repoPath,
  taskId,
  diffOptions,
  collapsedFiles,
  toggleFile,
  openFile,
  onDiscardFile,
  onStageFile,
  prUrl,
  commentThreads,
}: BuildPatchReviewItemsArgs): ReviewListItem[] {
  return files.map((fileDiff) => {
    const filePath = fileDiff.name ?? fileDiff.prevName ?? "";
    const key = makeFileKey(staged, filePath);
    const isCollapsed = collapsedFiles.has(key);
    const skipExpansion = computeSkipExpansion(
      staged,
      filePath,
      alsoStagedPaths,
    );

    return {
      key,
      scrollKey: key,
      filePaths: [filePath, fileDiff.prevName].filter(
        (path): path is string => !!path,
      ),
      node: (
        <PatchRow
          itemKey={key}
          filePath={filePath}
          fileDiff={fileDiff}
          repoPath={repoPath}
          taskId={taskId}
          diffOptions={diffOptions}
          collapsed={isCollapsed}
          skipExpansion={skipExpansion}
          toggleFile={toggleFile}
          openFile={openFile}
          onDiscardFile={onDiscardFile}
          onStageFile={onStageFile}
          staged={staged}
          prUrl={prUrl}
          commentThreads={commentThreads}
        />
      ),
    };
  });
}

interface BuildUntrackedReviewItemsArgs {
  files: ChangedFile[];
  repoPath: string;
  taskId: string;
  diffOptions: DiffOptions;
  collapsedFiles: Set<string>;
  toggleFile: (key: string) => void;
  onDiscardFile?: (key: string) => void;
  onStageFile?: (key: string) => void;
}

export function buildUntrackedReviewItems({
  files,
  repoPath,
  taskId,
  diffOptions,
  collapsedFiles,
  toggleFile,
  onDiscardFile,
  onStageFile,
}: BuildUntrackedReviewItemsArgs): ReviewListItem[] {
  return files.map((file) => {
    const key = makeFileKey(file.staged, file.path);
    const isCollapsed = collapsedFiles.has(key);

    return {
      key,
      scrollKey: key,
      filePaths: [file.path],
      node: (
        <UntrackedRow
          itemKey={key}
          file={file}
          repoPath={repoPath}
          taskId={taskId}
          diffOptions={diffOptions}
          collapsed={isCollapsed}
          toggleFile={toggleFile}
          onDiscardFile={onDiscardFile}
          onStageFile={onStageFile}
        />
      ),
    };
  });
}

interface BuildRemoteReviewItemsArgs {
  files: ChangedFile[];
  taskId: string;
  prUrl?: string | null;
  options: DiffOptions;
  collapsedFiles: Set<string>;
  toggleFile: (path: string) => void;
  commentThreads?: Map<number, PrCommentThread>;
}

export function buildRemoteReviewItems({
  files,
  taskId,
  prUrl,
  options,
  collapsedFiles,
  toggleFile,
  commentThreads,
}: BuildRemoteReviewItemsArgs): ReviewListItem[] {
  return files.map((file) => {
    const isCollapsed = collapsedFiles.has(file.path);
    const githubFileUrl = buildGithubFileUrl(prUrl, file.path);

    return {
      key: file.path,
      scrollKey: file.path,
      filePaths: [file.path, file.originalPath].filter(
        (path): path is string => !!path,
      ),
      node: (
        <RemoteRow
          file={file}
          taskId={taskId}
          prUrl={prUrl}
          options={options}
          collapsed={isCollapsed}
          toggleFile={toggleFile}
          commentThreads={commentThreads}
          externalUrl={githubFileUrl}
        />
      ),
    };
  });
}
