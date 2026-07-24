import { WorkerPoolContextProvider } from "@pierre/diffs/react";
import { useService } from "@posthog/di/react";
import type { Task } from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useCloudPrUrl } from "@posthog/ui/features/git-interaction/useCloudPrUrl";
import { useTaskPrStatus } from "@posthog/ui/features/sidebar/useTaskPrStatus";
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
  getEmptyReviewMessage,
  type ReviewListItem,
} from "../commentFileFilter";
import {
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

function ExpandedSidebar({ task }: { task: Task }) {
  const reviewHost = useService<ReviewHost>(REVIEW_HOST);
  const [width, setWidth] = useState(SIDEBAR_DEFAULT_WIDTH);
  const isDragging = useRef(false);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isDragging.current = true;
      const startX = e.clientX;
      const startWidth = width;

      const handleMouseMove = (e: MouseEvent) => {
        if (!isDragging.current) return;
        const delta = startX - e.clientX;
        const newWidth = Math.min(
          SIDEBAR_MAX_WIDTH,
          Math.max(SIDEBAR_MIN_WIDTH, startWidth + delta),
        );
        setWidth(newWidth);
      };

      const handleMouseUp = () => {
        isDragging.current = false;
        document.removeEventListener("mousemove", handleMouseMove);
        document.removeEventListener("mouseup", handleMouseUp);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };

      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    },
    [width],
  );

  return (
    <Flex direction="row" className="shrink-0">
      <button
        type="button"
        aria-label="Resize sidebar"
        onMouseDown={handleMouseDown}
        style={{ transition: "background 0.1s" }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "var(--accent-8)";
        }}
        onMouseLeave={(e) => {
          if (!isDragging.current) {
            e.currentTarget.style.background = "transparent";
          }
        }}
        className="w-[4px] shrink-0 cursor-col-resize border-l border-l-(--gray-6) bg-transparent p-0"
      />
      <Flex
        direction="column"
        style={{
          width: `${width}px`,
          minWidth: `${SIDEBAR_MIN_WIDTH}px`,
        }}
        className="shrink-0 bg-(--color-background)"
      >
        {reviewHost.renderExpandedSidebar(task)}
      </Flex>
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
  const lastActiveRef = useRef<string | null>(null);
  const pendingNavigationRef = useRef<string | null>(null);
  const navigationFrameRef = useRef<number | null>(null);
  const commentFilter = useReviewNavigationStore(
    (state) => state.commentFileFilters[taskId] ?? "none",
  );
  const setCommentFileFilter = useReviewNavigationStore(
    (state) => state.setCommentFileFilter,
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
  const visibleItemIndexByFilePath = useMemo(
    () => buildItemIndex(visibleItems),
    [visibleItems],
  );

  const workerFactory = useCallback(
    () => reviewHost.diffWorkerFactory(),
    [reviewHost],
  );

  const reviewMode = useReviewNavigationStore(
    (s) => s.reviewModes[taskId] ?? "closed",
  );
  const isExpanded = reviewMode === "expanded";

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
  const clearTask = useReviewNavigationStore((s) => s.clearTask);

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
  } else if (isEmpty || visibleItems.length === 0) {
    reviewContent = (
      <Flex align="center" justify="center" className="min-h-0 flex-1">
        <Text color="gray" className="text-sm">
          {getEmptyReviewMessage(activeCommentFilter)}
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
        data={visibleItems}
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
        <Flex direction="column" height="100%" id="review-shell">
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

            {isExpanded && <ExpandedSidebar task={task} />}
          </Flex>
        </Flex>
      </ReviewViewedContext.Provider>
    </WorkerPoolContextProvider>
  );
}
