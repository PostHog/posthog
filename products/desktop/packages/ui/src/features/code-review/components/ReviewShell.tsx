import { WorkerPoolContextProvider } from "@pierre/diffs/react";
import { useService } from "@posthog/di/react";
import type { Task } from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useCloudPrUrl } from "@posthog/ui/features/git-interaction/useCloudPrUrl";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";
import { useIsWiderThan } from "@posthog/ui/primitives/hooks/useObservedWidth";
import { ResizeHandle } from "@posthog/ui/primitives/ResizeHandle";
import { Flex, Spinner, Text } from "@radix-ui/themes";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { VList, type VListHandle } from "virtua";
import {
  deriveCommentFileFilterState,
  filterReviewItemsByViewedState,
  getEmptyReviewMessage,
  type ReviewListItem,
  resolveVisibleActiveFilePath,
} from "../commentFileFilter";
import {
  REVIEW_FILE_BROWSER_MIN_WIDTH,
  REVIEW_LIST_BUFFER_PX,
  REVIEW_LIST_ESTIMATED_ITEM_SIZE,
} from "../constants";
import { useReviewDraftsStore } from "../reviewDraftsStore";
import { REVIEW_HOST, type ReviewHost } from "../reviewHost";
import { useReviewNavigationStore } from "../reviewNavigationStore";
import type { ReviewShellProps } from "../reviewShellParts";
import {
  buildItemIndex,
  findActiveScrollKey,
  findRenderedScrollAnchor,
  isFileViewed,
} from "../reviewShellParts";
import { ReviewViewedContext } from "../reviewViewedContext";
import { useReviewViewedStore } from "../reviewViewedStore";
import { PendingReviewBar } from "./PendingReviewBar";
import { ReviewToolbar } from "./ReviewToolbar";

// Pure helpers, hooks, types, and presentational sub-components live in
// ../reviewShellParts. Re-exported here so consumers can import everything
// (ReviewShell + useReviewState + buildItemIndex + ReviewListItem) from a
// single "./ReviewShell" specifier.
export * from "../reviewShellParts";

const SIDEBAR_MIN_WIDTH = 200;
const SIDEBAR_MAX_WIDTH = 500;
const SIDEBAR_DEFAULT_WIDTH = 280;

function FileBrowser({ task }: { task: Task }) {
  const reviewHost = useService<ReviewHost>(REVIEW_HOST);
  const [width, setWidth] = useState(SIDEBAR_DEFAULT_WIDTH);
  const [isResizing, setIsResizing] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const rightRef = useRef(0);

  return (
    <Flex
      ref={boxRef}
      direction="column"
      style={{ width: `${width}px`, minWidth: `${SIDEBAR_MIN_WIDTH}px` }}
      className="relative shrink-0 border-l border-l-(--gray-6) bg-(--color-background)"
    >
      {reviewHost.renderFileBrowser(task)}
      <ResizeHandle
        edge="left"
        tooltip="Resize"
        isResizing={isResizing}
        setIsResizing={setIsResizing}
        onDragStart={() => {
          rightRef.current = boxRef.current?.getBoundingClientRect().right ?? 0;
        }}
        onDrag={(event) =>
          setWidth(
            Math.min(
              SIDEBAR_MAX_WIDTH,
              Math.max(SIDEBAR_MIN_WIDTH, rightRef.current - event.clientX),
            ),
          )
        }
      />
    </Flex>
  );
}

export function ReviewShell({
  task,
  fileCount,
  linesAdded,
  linesRemoved,
  isLoading,
  isEmpty,
  items,
  commentedFilePaths,
  unresolvedCommentedFilePaths,
  currentSignatures,
  viewedRecord,
  onToggleViewed,
  onUncollapseFile,
  onCollapseFiles,
  allExpanded,
  onExpandAll,
  onCollapseAll,
  onRefresh,
  onDiscardAll,
  effectiveSource,
  branchSourceAvailable,
  prSourceAvailable,
  defaultBranch,
}: ReviewShellProps) {
  const reviewHost = useService<ReviewHost>(REVIEW_HOST);
  const taskId = task.id;
  const listRef = useRef<VListHandle | null>(null);
  const listContainerRef = useRef<HTMLDivElement | null>(null);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const lastActiveRef = useRef<string | null>(null);
  const pendingNavigationRef = useRef<string | null>(null);
  const navigationFrameRef = useRef<number | null>(null);
  const commentFilter = useReviewNavigationStore(
    (state) => state.commentFileFilters[taskId] ?? "none",
  );
  const setCommentFileFilter = useReviewNavigationStore(
    (state) => state.setCommentFileFilter,
  );
  const hideViewedFiles = useReviewNavigationStore(
    (state) => state.hideViewedFiles[taskId] ?? false,
  );
  const setHideViewedFiles = useReviewNavigationStore(
    (state) => state.setHideViewedFiles,
  );
  const {
    activeFilter: activeCommentFilter,
    visibleItems,
    commentedFileCount,
    unresolvedCommentedFileCount,
  } = useMemo(
    () =>
      deriveCommentFileFilterState({
        items,
        requestedFilter: commentFilter,
        commentedFilePaths,
        unresolvedCommentedFilePaths,
      }),
    [commentFilter, commentedFilePaths, items, unresolvedCommentedFilePaths],
  );
  const filteredItems = useMemo(() => {
    if (!hideViewedFiles) return visibleItems;
    return filterReviewItemsByViewedState(
      visibleItems,
      currentSignatures,
      viewedRecord,
    );
  }, [currentSignatures, hideViewedFiles, viewedRecord, visibleItems]);
  const filteredFileCount = useMemo(
    () => filteredItems.filter((item) => item.filePaths).length,
    [filteredItems],
  );
  const visibleItemIndexByFilePath = useMemo(
    () => buildItemIndex(filteredItems),
    [filteredItems],
  );

  const workerFactory = useCallback(
    () => reviewHost.diffWorkerFactory(),
    [reviewHost],
  );

  // The room the review was given, not the mode it was opened in: the same
  // review is a column, a widened panel, and a scene of its own.
  const showFileBrowser = useIsWiderThan(
    shellRef,
    REVIEW_FILE_BROWSER_MIN_WIDTH,
  );

  const viewedCount = useMemo(() => {
    const visibleKeys =
      activeCommentFilter !== "none"
        ? new Set(
            visibleItems.flatMap((item) =>
              item.scrollKey ? [item.scrollKey] : [],
            ),
          )
        : null;
    let count = 0;
    for (const [key, sig] of currentSignatures) {
      if (visibleKeys && !visibleKeys.has(key)) continue;
      if (isFileViewed(viewedRecord[key], sig)) count++;
    }
    return count;
  }, [activeCommentFilter, currentSignatures, viewedRecord, visibleItems]);

  // Collapse already-viewed files on first open per task (mirrors GitHub).
  // Skips on re-opens: seededTaskRef prevents re-collapsing files the user
  // has manually expanded. Files changed since viewed stay expanded.
  const seededTaskRef = useRef<string | null>(null);
  useEffect(() => {
    if (seededTaskRef.current === taskId) return;
    if (currentSignatures.size === 0) return;
    seededTaskRef.current = taskId;
    const viewedKeys: string[] = [];
    for (const [key, sig] of currentSignatures) {
      if (isFileViewed(viewedRecord[key], sig)) viewedKeys.push(key);
    }
    if (viewedKeys.length > 0) onCollapseFiles(viewedKeys);
  }, [taskId, currentSignatures, viewedRecord, onCollapseFiles]);

  const clearTasks = useReviewViewedStore((s) => s.clearTasks);

  const archivedTaskIds = useArchivedTaskIds();
  useEffect(() => {
    const prunable = [...archivedTaskIds].filter((id) => id !== taskId);
    if (prunable.length > 0) clearTasks(prunable);
  }, [archivedTaskIds, clearTasks, taskId]);

  const cloudPrUrl = useCloudPrUrl(taskId);
  const { prState } = useTaskPrStatus({
    id: taskId,
    cloudPrUrl,
    taskRunEnvironment: task.latest_run?.environment,
  });
  useEffect(() => {
    if (prState === "merged") clearTasks([taskId]);
  }, [prState, taskId, clearTasks]);

  const viewedContextValue = useMemo(
    () => ({
      viewedRecord,
      currentSignatures,
      toggleViewed: onToggleViewed,
    }),
    [viewedRecord, currentSignatures, onToggleViewed],
  );

  const scrollRequest = useReviewNavigationStore(
    (s) => s.scrollRequests[taskId] ?? null,
  );
  const clearScrollRequest = useReviewNavigationStore(
    (s) => s.clearScrollRequest,
  );
  const setActiveFilePath = useReviewNavigationStore(
    (s) => s.setActiveFilePath,
  );
  const activeFilePath = useReviewNavigationStore(
    (s) => s.activeFilePaths[taskId] ?? null,
  );
  const clearTask = useReviewNavigationStore((s) => s.clearTask);

  useEffect(() => {
    if (!hideViewedFiles || !activeFilePath) return;
    const nextActiveFilePath = resolveVisibleActiveFilePath(
      filteredItems,
      activeFilePath,
    );
    if (nextActiveFilePath === activeFilePath) return;
    lastActiveRef.current = nextActiveFilePath;
    setActiveFilePath(taskId, nextActiveFilePath);
  }, [
    activeFilePath,
    filteredItems,
    hideViewedFiles,
    setActiveFilePath,
    taskId,
  ]);

  useEffect(() => {
    return () => {
      if (navigationFrameRef.current !== null) {
        cancelAnimationFrame(navigationFrameRef.current);
      }
      clearTask(taskId);
      useReviewDraftsStore.getState().clearDrafts(taskId);
    };
  }, [taskId, clearTask]);

  useEffect(() => {
    if (!scrollRequest) return;
    const targetIndex = visibleItemIndexByFilePath.get(scrollRequest);
    if (targetIndex === undefined) return;

    const currentSignature = currentSignatures.get(scrollRequest);
    const viewed =
      currentSignature !== undefined &&
      isFileViewed(viewedRecord[scrollRequest], currentSignature);
    if (navigationFrameRef.current !== null) {
      cancelAnimationFrame(navigationFrameRef.current);
    }
    pendingNavigationRef.current = scrollRequest;
    if (!viewed) onUncollapseFile?.(scrollRequest);

    const scrollToAnchor = (remainingAttempts: number) => {
      listRef.current?.scrollToIndex(targetIndex, { align: "start" });
      navigationFrameRef.current = requestAnimationFrame(() => {
        const root = listContainerRef.current;
        const anchor = root
          ? findRenderedScrollAnchor(root, scrollRequest)
          : null;

        if (!anchor && remainingAttempts > 0) {
          scrollToAnchor(remainingAttempts - 1);
          return;
        }

        anchor?.scrollIntoView({ block: "start", inline: "nearest" });
        lastActiveRef.current = scrollRequest;
        setActiveFilePath(taskId, scrollRequest);
        clearScrollRequest(taskId);
        navigationFrameRef.current = requestAnimationFrame(() => {
          pendingNavigationRef.current = null;
          navigationFrameRef.current = null;
        });
      });
    };

    scrollToAnchor(5);
  }, [
    clearScrollRequest,
    currentSignatures,
    onUncollapseFile,
    scrollRequest,
    setActiveFilePath,
    taskId,
    visibleItemIndexByFilePath,
    viewedRecord,
  ]);

  const handleScroll = useCallback(() => {
    if (pendingNavigationRef.current !== null) return;
    const scrollRoot = listContainerRef.current?.querySelector<HTMLElement>(
      ".pierre-scroll-root",
    );
    if (!scrollRoot) return;
    const scrollKey = findActiveScrollKey(scrollRoot);
    if (!scrollKey || scrollKey === lastActiveRef.current) return;
    lastActiveRef.current = scrollKey;
    setActiveFilePath(taskId, scrollKey);
  }, [setActiveFilePath, taskId]);

  const renderItem = useCallback(
    (item: ReviewListItem) => (
      <div
        key={item.key}
        data-scroll-key={item.scrollKey}
        className="pb-2 last:pb-0"
      >
        {item.node}
      </div>
    ),
    [],
  );

  let reviewContent: ReactNode;
  if (isLoading) {
    reviewContent = (
      <Flex align="center" justify="center" className="min-h-0 flex-1">
        <Spinner size="2" />
      </Flex>
    );
  } else if (isEmpty || filteredItems.length === 0) {
    reviewContent = (
      <Flex align="center" justify="center" className="min-h-0 flex-1">
        <Text color="gray" className="text-sm">
          {hideViewedFiles
            ? "No unviewed file changes"
            : getEmptyReviewMessage(activeCommentFilter)}
        </Text>
      </Flex>
    );
  } else {
    reviewContent = (
      <VList
        ref={listRef}
        bufferSize={REVIEW_LIST_BUFFER_PX}
        itemSize={REVIEW_LIST_ESTIMATED_ITEM_SIZE}
        className="pierre-scroll-root scrollbar-overlay-y min-h-0 flex-1 overflow-auto bg-(--gray-2)"
        shift={false}
        style={{ scrollbarGutter: "stable" }}
        onScroll={handleScroll}
        data={filteredItems}
      >
        {renderItem}
      </VList>
    );
  }

  return (
    <WorkerPoolContextProvider
      // poolSize: each highlighter worker is a full V8 isolate with shiki
      // grammars loaded (~40MB RSS); the library default of 8 is oversized.
      poolOptions={{ workerFactory, poolSize: 2 }}
      highlighterOptions={{
        theme: { dark: "github-dark", light: "github-light" },
        langs: [
          "typescript",
          "tsx",
          "javascript",
          "jsx",
          "json",
          "css",
          "html",
          "markdown",
          "python",
          "ruby",
          "go",
          "rust",
          "shell",
          "yaml",
          "sql",
        ],
      }}
    >
      <ReviewViewedContext.Provider value={viewedContextValue}>
        <Flex ref={shellRef} direction="column" height="100%" id="review-shell">
          <ReviewToolbar
            taskId={taskId}
            fileCount={fileCount}
            viewedCount={viewedCount}
            commentedFileCount={commentedFileCount}
            unresolvedCommentedFileCount={unresolvedCommentedFileCount}
            commentFilter={activeCommentFilter}
            onCommentFilterChange={
              commentedFilePaths && unresolvedCommentedFilePaths
                ? (filter) => setCommentFileFilter(taskId, filter)
                : undefined
            }
            hideViewedFiles={hideViewedFiles}
            filteredFileCount={filteredFileCount}
            onHideViewedFilesChange={(hideViewed) =>
              setHideViewedFiles(taskId, hideViewed)
            }
            linesAdded={linesAdded}
            linesRemoved={linesRemoved}
            allExpanded={allExpanded}
            onExpandAll={onExpandAll}
            onCollapseAll={onCollapseAll}
            onRefresh={onRefresh}
            onDiscardAll={onDiscardAll}
            effectiveSource={effectiveSource}
            branchSourceAvailable={branchSourceAvailable}
            prSourceAvailable={prSourceAvailable}
            defaultBranch={defaultBranch}
          />
          <Flex className="min-h-0 flex-1">
            <Flex
              ref={listContainerRef}
              direction="column"
              className="min-w-0 flex-1"
            >
              {reviewContent}
              <PendingReviewBar taskId={taskId} />
            </Flex>

            {showFileBrowser && <FileBrowser task={task} />}
          </Flex>
        </Flex>
      </ReviewViewedContext.Provider>
    </WorkerPoolContextProvider>
  );
}
