import { buildToolCallFallbacks } from "@posthog/core/code-review/buildToolCallFallbacks";
import { buildGithubFileUrl } from "@posthog/core/code-review/reviewItemKeys";
import { extractCloudFileDiff } from "@posthog/core/task-detail/cloudToolChanges";
import type { Task } from "@posthog/shared/domain-types";
import { Flex, Spinner, Text } from "@radix-ui/themes";
import { useMemo } from "react";
import { useDiffViewerStore } from "../../code-editor/diffViewerStore";
import { usePrDetails } from "../../git-interaction/usePrDetails";
import { useCloudChangedFiles } from "../../task-detail/hooks/useCloudChangedFiles";
import {
  getCommentedFilePaths,
  type ReviewListItem,
} from "../commentFileFilter";
import { useReviewNavigationStore } from "../reviewNavigationStore";
import { PatchedFileDiff } from "./PatchedFileDiff";
import { ReviewShell, useReviewState } from "./ReviewShell";
import { changedFileSignature } from "./reviewItemBuilders";

interface CloudReviewPageProps {
  task: Task;
}

export function CloudReviewPage({ task }: CloudReviewPageProps) {
  const taskId = task.id;
  const isReviewOpen = useReviewNavigationStore(
    (s) => (s.reviewModes[taskId] ?? "closed") !== "closed",
  );
  const showReviewComments = useDiffViewerStore((s) => s.showReviewComments);
  const {
    effectiveBranch,
    prUrl,
    isRunActive,
    remoteFiles,
    reviewFiles,
    toolCalls,
    isLoading,
  } = useCloudChangedFiles(taskId, task, isReviewOpen);
  const { commentThreads, commentsLoading } = usePrDetails(prUrl, {
    includeComments: isReviewOpen && showReviewComments,
  });
  const commentedFilePaths = useMemo(
    () =>
      prUrl && !commentsLoading
        ? getCommentedFilePaths(commentThreads)
        : undefined,
    [commentThreads, commentsLoading, prUrl],
  );

  const allPaths = useMemo(() => reviewFiles.map((f) => f.path), [reviewFiles]);

  const {
    diffOptions,
    linesAdded,
    linesRemoved,
    collapsedFiles,
    toggleFile,
    expandAll,
    collapseAll,
    uncollapseFile,
    collapseFiles,
    viewedRecord,
    toggleViewed,
  } = useReviewState(reviewFiles, allPaths, taskId);

  const currentSignatures = useMemo(() => {
    const map = new Map<string, string>();
    for (const f of reviewFiles) {
      const signature = changedFileSignature(f);
      if (signature) map.set(f.path, signature);
    }
    return map;
  }, [reviewFiles]);

  const toolCallFallbacks = useMemo(
    () =>
      buildToolCallFallbacks(
        remoteFiles.length > 0,
        reviewFiles.map((f) => f.path),
        (path) => extractCloudFileDiff(toolCalls, path) ?? undefined,
      ),
    [remoteFiles.length, toolCalls, reviewFiles],
  );

  const items = useMemo<ReviewListItem[]>(() => {
    return reviewFiles.map((file) => {
      const isCollapsed = collapsedFiles.has(file.path);
      const githubFileUrl = buildGithubFileUrl(prUrl, file.path);

      return {
        key: file.path,
        scrollKey: file.path,
        filePaths: [file.path, file.originalPath].filter(
          (path): path is string => !!path,
        ),
        node: (
          <PatchedFileDiff
            file={file}
            taskId={taskId}
            prUrl={prUrl}
            options={diffOptions}
            collapsed={isCollapsed}
            onToggle={() => toggleFile(file.path)}
            commentThreads={showReviewComments ? commentThreads : undefined}
            fallback={toolCallFallbacks?.get(file.path) ?? null}
            externalUrl={githubFileUrl}
            viewedKey={file.path}
          />
        ),
      };
    });
  }, [
    collapsedFiles,
    commentThreads,
    diffOptions,
    prUrl,
    reviewFiles,
    showReviewComments,
    taskId,
    toggleFile,
    toolCallFallbacks,
  ]);

  if (!prUrl && !effectiveBranch && reviewFiles.length === 0) {
    if (isRunActive) {
      return (
        <Flex
          align="center"
          justify="center"
          height="100%"
          className="text-gray-10"
        >
          <Flex direction="column" align="center" gap="2">
            <Spinner size="2" />
            <Text className="text-sm">Waiting for changes...</Text>
          </Flex>
        </Flex>
      );
    }
    return null;
  }

  return (
    <ReviewShell
      task={task}
      fileCount={reviewFiles.length}
      linesAdded={linesAdded}
      linesRemoved={linesRemoved}
      isLoading={isLoading && reviewFiles.length === 0}
      isEmpty={reviewFiles.length === 0}
      allExpanded={collapsedFiles.size === 0}
      onExpandAll={expandAll}
      onCollapseAll={collapseAll}
      onUncollapseFile={uncollapseFile}
      onCollapseFiles={collapseFiles}
      items={items}
      commentedFilePaths={commentedFilePaths?.all}
      unresolvedCommentedFilePaths={commentedFilePaths?.unresolved}
      currentSignatures={currentSignatures}
      viewedRecord={viewedRecord}
      onToggleViewed={toggleViewed}
    />
  );
}
