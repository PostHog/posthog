import {
  ArrowCounterClockwise,
  ArrowSquareOut,
  CaretDown,
  ChatCircle,
  CheckSquare,
  Minus,
  Plus,
  Square,
} from "@phosphor-icons/react";
import type { FileDiffMetadata } from "@pierre/diffs/react";
import type { ResolvedDiffSource } from "@posthog/core/code-review/resolveDiffSource";
import {
  type DeferredReason,
  getDeferredMessage,
  splitFilePath,
  sumHunkStats,
} from "@posthog/core/code-review/reviewShellGeometry";
import { Badge } from "@posthog/quill";
import type { ChangedFile, Task } from "@posthog/shared/domain-types";
import { type ReactNode, useCallback, useMemo, useState } from "react";
import { FileIcon } from "../../primitives/FileIcon";
import { Tooltip } from "../../primitives/Tooltip";
import { useThemeStore } from "../../shell/themeStore";
import { useDiffViewerStore } from "../code-editor/diffViewerStore";
import { computeDiffStats } from "../git-interaction/utils/diffStats";
import type { ReviewListItem } from "./commentFileFilter";
import { useReviewViewedContext } from "./reviewViewedContext";
import { useReviewViewedStore } from "./reviewViewedStore";

export type { DeferredReason } from "@posthog/core/code-review/reviewShellGeometry";
export {
  buildItemIndex,
  splitFilePath,
} from "@posthog/core/code-review/reviewShellGeometry";
export type { ReviewListItem } from "./commentFileFilter";

const STICKY_HEADER_CSS = `[data-diffs-header] { position: sticky; top: 0; z-index: 1; background: var(--gray-2); }`;
const SCROLL_ANCHOR_SELECTOR = "[data-scroll-key]";

export function findRenderedScrollAnchor(
  root: HTMLElement,
  scrollKey: string,
): HTMLElement | null {
  for (const anchor of root.querySelectorAll<HTMLElement>(
    SCROLL_ANCHOR_SELECTOR,
  )) {
    if (anchor.dataset.scrollKey === scrollKey) return anchor;
  }
  return null;
}

export function findActiveScrollKey(root: HTMLElement): string | null {
  const rootTop = root.getBoundingClientRect().top;
  let activeScrollKey: string | null = null;
  for (const anchor of root.querySelectorAll<HTMLElement>(
    SCROLL_ANCHOR_SELECTOR,
  )) {
    const scrollKey = anchor.dataset.scrollKey;
    if (!scrollKey) continue;
    if (anchor.getBoundingClientRect().top <= rootTop + 1) {
      activeScrollKey = scrollKey;
      continue;
    }
    return activeScrollKey ?? scrollKey;
  }
  return activeScrollKey;
}

export function useDiffOptions() {
  const viewMode = useDiffViewerStore((s) => s.viewMode);
  const wordWrap = useDiffViewerStore((s) => s.wordWrap);
  const loadFullFiles = useDiffViewerStore((s) => s.loadFullFiles);
  const wordDiffs = useDiffViewerStore((s) => s.wordDiffs);
  const isDarkMode = useThemeStore((s) => s.isDarkMode);

  return useMemo(
    () => ({
      diffStyle: viewMode as "split" | "unified",
      overflow: (wordWrap ? "wrap" : "scroll") as "wrap" | "scroll",
      expandUnchanged: loadFullFiles,
      lineDiffType: (wordDiffs ? "word-alt" : "none") as "word-alt" | "none",
      themeType: (isDarkMode ? "dark" : "light") as "dark" | "light",
      theme: { dark: "github-dark" as const, light: "github-light" as const },
      unsafeCSS: STICKY_HEADER_CSS,
    }),
    [viewMode, wordWrap, loadFullFiles, wordDiffs, isDarkMode],
  );
}

export function useReviewState(
  changedFiles: ChangedFile[],
  allPaths: string[],
  taskId: string,
) {
  const diffOptions = useDiffOptions();

  const { linesAdded, linesRemoved } = useMemo(
    () => computeDiffStats(changedFiles),
    [changedFiles],
  );

  const collapseState = useCollapseState(allPaths);
  const viewedState = useViewedState(taskId, collapseState.setFileCollapsed);

  return {
    diffOptions,
    linesAdded,
    linesRemoved,
    ...collapseState,
    ...viewedState,
  };
}

const EMPTY_VIEWED_RECORD: Record<string, string> = {};

function useViewedState(
  taskId: string,
  setFileCollapsed: (filePath: string, collapsed: boolean) => void,
) {
  const viewedRecord =
    useReviewViewedStore((s) => s.viewed[taskId]) ?? EMPTY_VIEWED_RECORD;
  const setViewed = useReviewViewedStore((s) => s.setViewed);

  const toggleViewed = useCallback(
    (key: string, nextSig: string | null) => {
      setViewed(taskId, key, nextSig);
      setFileCollapsed(key, nextSig !== null);
    },
    [taskId, setViewed, setFileCollapsed],
  );

  return { viewedRecord, toggleViewed };
}

function useCollapseState(filePaths: string[]) {
  const [collapsedFiles, setCollapsedFiles] = useState<Set<string>>(
    () => new Set(),
  );

  const toggleFile = useCallback((filePath: string) => {
    setCollapsedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(filePath)) next.delete(filePath);
      else next.add(filePath);
      return next;
    });
  }, []);

  const uncollapseFile = useCallback((filePath: string) => {
    setCollapsedFiles((prev) => {
      if (!prev.has(filePath)) return prev;
      const next = new Set(prev);
      next.delete(filePath);
      return next;
    });
  }, []);

  const setFileCollapsed = useCallback(
    (filePath: string, collapsed: boolean) => {
      setCollapsedFiles((prev) => {
        if (collapsed === prev.has(filePath)) return prev;
        const next = new Set(prev);
        if (collapsed) next.add(filePath);
        else next.delete(filePath);
        return next;
      });
    },
    [],
  );

  const collapseFiles = useCallback((keys: Iterable<string>) => {
    setCollapsedFiles((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const key of keys) {
        if (!next.has(key)) {
          next.add(key);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);

  const expandAll = useCallback(() => setCollapsedFiles(new Set()), []);

  const collapseAll = useCallback(
    () => setCollapsedFiles(new Set(filePaths)),
    [filePaths],
  );

  return {
    collapsedFiles,
    toggleFile,
    uncollapseFile,
    setFileCollapsed,
    collapseFiles,
    expandAll,
    collapseAll,
  };
}

export interface ReviewShellProps {
  task: Task;
  fileCount: number;
  linesAdded: number;
  linesRemoved: number;
  isLoading: boolean;
  isEmpty: boolean;
  items: ReviewListItem[];
  commentedFilePaths?: ReadonlySet<string>;
  unresolvedCommentedFilePaths?: ReadonlySet<string>;
  currentSignatures: Map<string, string>;
  viewedRecord: Record<string, string>;
  onToggleViewed: (key: string, sig: string | null) => void;
  onUncollapseFile?: (filePath: string) => void;
  onCollapseFiles: (keys: string[]) => void;
  allExpanded: boolean;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  onRefresh?: () => void;
  onDiscardAll?: () => void;
  effectiveSource?: ResolvedDiffSource;
  branchSourceAvailable?: boolean;
  prSourceAvailable?: boolean;
  defaultBranch?: string | null;
}

export function FileHeaderRow({
  dirPath,
  fileName,
  additions,
  deletions,
  collapsed,
  onToggle,
  commentCount,
  trailing,
  viewedKey,
}: {
  dirPath: string;
  fileName: string;
  additions: number;
  deletions: number;
  collapsed: boolean;
  onToggle: () => void;
  commentCount?: number;
  trailing?: ReactNode;
  viewedKey?: string;
}) {
  return (
    <div className="flex w-full items-center gap-[6px] border-b border-b-(--gray-5) px-[12px] py-[6px] font-[var(--code-font-family)] text-xs">
      <button
        type="button"
        onClick={onToggle}
        className="flex min-w-0 flex-1 cursor-pointer items-center gap-[6px] border-0 bg-transparent p-0 text-left"
      >
        <CaretDown
          size={12}
          color="var(--gray-9)"
          style={{
            transform: collapsed ? "rotate(-90deg)" : "rotate(0deg)",
            transition: "transform 0.15s",
          }}
          className="shrink-0"
        />
        <FileIcon filename={fileName} size={14} />
        <span
          title={dirPath + fileName}
          className="flex min-w-0 flex-1 gap-[6px]"
        >
          <span className="shrink-0 whitespace-nowrap font-semibold">
            {fileName}
          </span>
          <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap text-(--gray-9)">
            {dirPath}
          </span>
        </span>
        {commentCount != null && commentCount > 0 && (
          <PrCommentCountBadge count={commentCount} />
        )}
        <span className="font-mono text-[10px]">
          {additions > 0 && (
            <span className="mr-[2px] text-(--green-9)">+{additions}</span>
          )}
          {deletions > 0 && (
            <span className="text-(--red-9)">-{deletions}</span>
          )}
        </span>
      </button>
      {trailing}
      {viewedKey !== undefined && <ViewedCheckbox viewedKey={viewedKey} />}
    </div>
  );
}

export function isFileViewed(
  storedSig: string | undefined,
  currentSig: string,
): boolean {
  return storedSig === currentSig;
}

function ViewedCheckbox({ viewedKey }: { viewedKey: string }) {
  const ctx = useReviewViewedContext();
  if (!ctx) return null;

  const current = ctx.currentSignatures.get(viewedKey);
  if (current === undefined) return null;

  const stored = ctx.viewedRecord[viewedKey];
  const viewed = isFileViewed(stored, current);
  const changed = stored !== undefined && !viewed;
  let title = "Mark as viewed";
  if (changed) {
    title = "Changed since you viewed it: click to mark as viewed again";
  } else if (viewed) {
    title = "Mark as not viewed";
  }

  return (
    <button
      type="button"
      aria-pressed={viewed}
      aria-label="Viewed"
      title={title}
      onClick={(e) => {
        e.stopPropagation();
        ctx.toggleViewed(viewedKey, viewed ? null : current);
      }}
      className="ml-[6px] flex shrink-0 cursor-pointer items-center gap-[4px] rounded-[4px] border border-(--gray-6) bg-(--gray-3) px-[8px] py-[2px] text-(--gray-11) text-xs hover:bg-(--gray-4)"
    >
      {viewed ? (
        <CheckSquare size={14} weight="fill" color="var(--accent-9)" />
      ) : (
        <Square size={14} color={changed ? "var(--amber-9)" : undefined} />
      )}
      <span className={changed ? "text-(--amber-11)" : undefined}>
        {changed ? "Changed" : "Viewed"}
      </span>
    </button>
  );
}

export function OpenFileButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="ml-auto inline-flex cursor-pointer rounded-[3px] border-0 bg-transparent p-[2px] text-(--gray-9) hover:bg-gray-4"
    >
      <ArrowSquareOut size={14} />
    </button>
  );
}

export function DiffFileHeader({
  fileDiff,
  collapsed,
  onToggle,
  onOpenFile,
  onDiscard,
  onStage,
  staged,
  viewedKey,
  commentCount,
  trailing,
}: {
  fileDiff: FileDiffMetadata;
  collapsed: boolean;
  onToggle: () => void;
  onOpenFile?: () => void;
  onDiscard?: () => void;
  onStage?: () => void;
  staged?: boolean;
  viewedKey?: string;
  commentCount?: number;
  /** Extra controls rendered after the action buttons (e.g. a "Viewed" toggle). */
  trailing?: ReactNode;
}) {
  const fullPath =
    fileDiff.prevName && fileDiff.prevName !== fileDiff.name
      ? `${fileDiff.prevName} → ${fileDiff.name}`
      : fileDiff.name;
  const { dirPath, fileName } = splitFilePath(fullPath ?? "");
  const { additions, deletions } = sumHunkStats(fileDiff.hunks);

  return (
    <FileHeaderRow
      dirPath={dirPath}
      fileName={fileName}
      additions={additions}
      deletions={deletions}
      collapsed={collapsed}
      onToggle={onToggle}
      viewedKey={viewedKey}
      commentCount={commentCount}
      trailing={
        (onStage || onDiscard || onOpenFile || trailing) && (
          <span className="ml-auto inline-flex items-center gap-[2px]">
            {onStage && (
              <Tooltip content={staged ? "Unstage" : "Stage"}>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onStage();
                  }}
                  className="inline-flex cursor-pointer rounded-[3px] border-0 bg-transparent p-[2px] text-(--gray-9) hover:bg-gray-4"
                >
                  {staged ? <Minus size={14} /> : <Plus size={14} />}
                </button>
              </Tooltip>
            )}
            {onDiscard && (
              <Tooltip content="Discard changes">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDiscard();
                  }}
                  className="inline-flex cursor-pointer rounded-[3px] border-0 bg-transparent p-[2px] text-(--gray-9) hover:bg-gray-4"
                >
                  <ArrowCounterClockwise size={14} />
                </button>
              </Tooltip>
            )}
            {onOpenFile && (
              <Tooltip content="Open file">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpenFile();
                  }}
                  className="inline-flex cursor-pointer rounded-[3px] border-0 bg-transparent p-[2px] text-(--gray-9) hover:bg-gray-4"
                >
                  <ArrowSquareOut size={14} />
                </button>
              </Tooltip>
            )}
            {trailing}
          </span>
        )
      }
    />
  );
}

export function DeferredDiffPlaceholder({
  filePath,
  linesAdded,
  linesRemoved,
  reason,
  collapsed,
  onToggle,
  onShow,
  externalUrl,
  viewedKey,
  commentCount,
  headerTrailing,
}: {
  filePath: string;
  linesAdded: number;
  linesRemoved: number;
  reason: DeferredReason;
  collapsed: boolean;
  onToggle: () => void;
  onShow?: () => void;
  externalUrl?: string;
  viewedKey?: string;
  commentCount?: number;
  /** Extra controls in the header row (e.g. a "Viewed" toggle). */
  headerTrailing?: ReactNode;
}) {
  const { dirPath, fileName } = splitFilePath(filePath);

  return (
    <div>
      <FileHeaderRow
        dirPath={dirPath}
        fileName={fileName}
        additions={linesAdded}
        deletions={linesRemoved}
        collapsed={collapsed}
        onToggle={onToggle}
        viewedKey={viewedKey}
        commentCount={commentCount}
        trailing={
          headerTrailing && (
            <span className="ml-auto inline-flex items-center">
              {headerTrailing}
            </span>
          )
        }
      />
      {!collapsed && (
        <div className="w-full border-b border-b-(--gray-5) bg-(--gray-2) p-[16px] text-center text-(--gray-9) text-xs">
          {getDeferredMessage(reason)}
          {onShow ? (
            <>
              {" "}
              <button
                type="button"
                onClick={onShow}
                style={{
                  fontSize: "inherit",
                }}
                className="cursor-pointer border-0 bg-transparent p-0 text-(--accent-9) underline"
              >
                Load diff
              </button>
            </>
          ) : externalUrl ? (
            <>
              {" "}
              <a
                href={externalUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  fontSize: "inherit",
                }}
                className="text-(--accent-9) underline"
              >
                View on GitHub
              </a>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}

function PrCommentCountBadge({ count }: { count: number }) {
  const label = `${count} comment${count === 1 ? "" : "s"}`;
  return (
    <Badge
      variant="default"
      title={label}
      className="shrink-0 gap-[3px] border-(--gray-7) bg-(--gray-3) text-[11px] text-gray-12 tabular-nums"
    >
      <ChatCircle size={12} weight="fill" />
      {count}
      <span className="sr-only"> comment{count === 1 ? "" : "s"}</span>
    </Badge>
  );
}
