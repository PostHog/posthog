import {
  ChatCircleIcon,
  GitDiffIcon,
  PackageIcon,
} from "@phosphor-icons/react";
import {
  Button,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { TaskArtifactsList } from "@posthog/ui/features/canvas/components/TaskArtifactsList";
import { TaskCommentsList } from "@posthog/ui/features/canvas/components/TaskCommentsList";
import { ThreadLoadingState } from "@posthog/ui/features/canvas/components/ThreadPanel";
import { useThreadConversation } from "@posthog/ui/features/canvas/hooks/useThreadConversation";
import {
  LazyCloudReviewPage as CloudReviewPage,
  LazyReviewPage as ReviewPage,
} from "@posthog/ui/features/code-review/components/LazyReviewPages";
import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useWorkspace } from "@posthog/ui/features/workspace/useWorkspace";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { useParams } from "@tanstack/react-router";
import { type ReactNode, useEffect, useRef } from "react";
import type { RightPanelSide } from "../navPanelSearch";
import { RIGHT_PANEL_MIN_WIDTH, useRightPanelStore } from "../rightPanelStore";
import { patchNavPanelSearch, useNavPanelSearch } from "../useNavPanels";

const SESSIONLESS_KEY = "__none";

/** The task the right panel talks about: the one on the current route. */
function useRightPanelTask(): Task | null {
  const params = useParams({ strict: false });
  const taskId = params.taskId ?? null;
  const { data: tasks } = useTasks();
  if (!taskId) return null;
  return tasks?.find((t) => t.id === taskId) ?? null;
}

/**
 * Which panel is open. The URL's `side` param wins; without it, an open review
 * mode (set by every existing "open review" entry point) reads as Changes.
 */
function useActiveSide(taskId: string | null): RightPanelSide | null {
  const search = useNavPanelSearch();
  const reviewMode = useReviewNavigationStore((s) =>
    taskId ? (s.reviewModes[taskId] ?? "closed") : "closed",
  );
  if (search.side !== "none") return search.side;
  if (taskId && reviewMode !== "closed") return "changes";
  return null;
}

function toggleSide(
  side: RightPanelSide,
  active: RightPanelSide | null,
  taskId: string | null,
): void {
  const { setSideForKey } = useRightPanelStore.getState();
  const { setReviewMode } = useReviewNavigationStore.getState();
  const key = taskId ?? SESSIONLESS_KEY;

  if (active === side) {
    patchNavPanelSearch({ side: "none" });
    if (taskId) setReviewMode(taskId, "closed");
    setSideForKey(key, undefined);
    return;
  }

  setSideForKey(key, side);
  if (side === "changes" && taskId) {
    // Changes rides the review store so the command menu, PR links, and diff
    // toggles that already open review all land on the same panel.
    patchNavPanelSearch({ side: "none" });
    setReviewMode(taskId, "split");
    return;
  }
  patchNavPanelSearch({ side });
  if (taskId) setReviewMode(taskId, "closed");
}

const SIDE_LABELS: Record<RightPanelSide, string> = {
  artifacts: "Artifacts",
  comments: "Comments",
  changes: "Changes",
};

/**
 * The always-there buttons in the header band. The panel opens beneath them;
 * one at a time, the active button toggles closed.
 */
export function RightPanelButtons() {
  const task = useRightPanelTask();
  const taskId = task?.id ?? null;
  const active = useActiveSide(taskId);

  const button = (side: RightPanelSide, icon: ReactNode) => (
    <Tooltip key={side}>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            aria-label={SIDE_LABELS[side]}
            data-selected={active === side || undefined}
            onClick={() => toggleSide(side, active, taskId)}
            className={cn(
              "text-muted-foreground",
              active === side && "bg-fill-selected text-foreground",
            )}
          >
            {icon}
          </Button>
        }
      />
      <TooltipContent side="bottom">{SIDE_LABELS[side]}</TooltipContent>
    </Tooltip>
  );

  return (
    <TooltipProvider delay={400}>
      <div className="flex shrink-0 items-center gap-0.5">
        {button("artifacts", <PackageIcon size={16} />)}
        {button("comments", <ChatCircleIcon size={16} />)}
        {button("changes", <GitDiffIcon size={16} />)}
      </div>
    </TooltipProvider>
  );
}

function SidePanelEmpty({ side }: { side: RightPanelSide }) {
  const description =
    side === "artifacts"
      ? "Open a session to see the artifacts it produced."
      : side === "comments"
        ? "Open a session to read and reply to its comments."
        : "Open a session to review its changes.";
  return (
    <Empty className="border-0 py-10">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          {side === "artifacts" ? (
            <PackageIcon size={18} />
          ) : side === "comments" ? (
            <ChatCircleIcon size={18} />
          ) : (
            <GitDiffIcon size={18} />
          )}
        </EmptyMedia>
        <EmptyTitle>No session open</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

/** Artifacts and comments share the thread's timeline, loaded once here. */
function TaskSidePanelContent({
  task,
  side,
}: {
  task: Task;
  side: "artifacts" | "comments";
}) {
  const { timeline, isReady } = useThreadConversation(task, {
    surface: "activity_panel",
  });
  if (!isReady) return <ThreadLoadingState />;
  if (side === "comments") {
    return <TaskCommentsList task={task} timeline={timeline} />;
  }
  return <TaskArtifactsList task={task} timeline={timeline} canOpenInPlace />;
}

function ChangesPanelContent({ task }: { task: Task }) {
  const workspace = useWorkspace(task.id);
  const isCloud =
    workspace?.mode === "cloud" || task.latest_run?.environment === "cloud";
  return isCloud ? <CloudReviewPage task={task} /> : <ReviewPage task={task} />;
}

/**
 * The right panel column: a push column under the header-band buttons, one
 * panel at a time, shared resizable width. Open state is per-session (the
 * store remembers each session's panel; the URL's `side` param wins on load).
 */
export function RightPanel() {
  const task = useRightPanelTask();
  const taskId = task?.id ?? null;
  const active = useActiveSide(taskId);
  const search = useNavPanelSearch();

  const width = useRightPanelStore((s) => s.width);
  const setWidth = useRightPanelStore((s) => s.setWidth);
  const isResizing = useRightPanelStore((s) => s.isResizing);
  const setIsResizing = useRightPanelStore((s) => s.setIsResizing);

  // Per-session memory: on the first render the URL wins and seeds the
  // session's memory; on later session switches the new session's remembered
  // panel is applied (or none, closing the panel).
  const key = taskId ?? SESSIONLESS_KEY;
  const seededRef = useRef(false);
  const lastKeyRef = useRef(key);
  const urlSide = search.side === "none" ? null : search.side;
  useEffect(() => {
    const store = useRightPanelStore.getState();
    if (!seededRef.current) {
      seededRef.current = true;
      lastKeyRef.current = key;
      if (urlSide) store.setSideForKey(key, urlSide);
      return;
    }
    if (lastKeyRef.current === key) return;
    lastKeyRef.current = key;
    const remembered = store.sideByKey[key];
    const { setReviewMode } = useReviewNavigationStore.getState();
    if (remembered === "changes" && taskId) {
      patchNavPanelSearch({ side: "none" });
      setReviewMode(taskId, "split");
      return;
    }
    patchNavPanelSearch({ side: remembered ?? "none" });
    // Review mode is already per-task, so a session switch restores it on its
    // own — only an explicit non-changes panel needs it closed.
    if (remembered && taskId) setReviewMode(taskId, "closed");
  }, [key, taskId, urlSide]);

  return (
    <ResizableSidebar
      open={active != null}
      width={width}
      setWidth={setWidth}
      isResizing={isResizing}
      setIsResizing={setIsResizing}
      side="right"
      minWidth={RIGHT_PANEL_MIN_WIDTH}
    >
      <div className="flex h-full min-h-0 flex-col bg-background">
        {active && (
          <div className="flex h-[32px] shrink-0 items-center border-border border-b px-3">
            <span className="font-medium text-[13px]">
              {SIDE_LABELS[active]}
            </span>
          </div>
        )}
        <div className="min-h-0 flex-1 overflow-hidden">
          {active === "changes" &&
            (task ? (
              <ChangesPanelContent task={task} />
            ) : (
              <SidePanelEmpty side="changes" />
            ))}
          {(active === "artifacts" || active === "comments") &&
            (task ? (
              <TaskSidePanelContent task={task} side={active} />
            ) : (
              <SidePanelEmpty side={active} />
            ))}
        </div>
      </div>
    </ResizableSidebar>
  );
}
