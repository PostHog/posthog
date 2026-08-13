import {
  ChatCircleIcon,
  GitDiffIcon,
  PackageIcon,
  PulseIcon,
} from "@phosphor-icons/react";
import {
  Button,
  cn,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { Task } from "@posthog/shared/domain-types";
import { ActivityPanelBody } from "@posthog/ui/features/canvas/components/ActivityPanelBody";
import {
  LazyCloudReviewPage as CloudReviewPage,
  LazyReviewPage as ReviewPage,
} from "@posthog/ui/features/code-review/components/LazyReviewPages";
import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useWorkspace } from "@posthog/ui/features/workspace/useWorkspace";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { type ReactNode, useEffect, useRef, useState } from "react";
import {
  DEFAULT_RIGHT_PANEL_SIDE,
  RIGHT_PANEL_MIN_WIDTH,
  type RightPanelSide,
  resolveRightPanelSide,
  useRightPanelStore,
} from "../rightPanelStore";

const SESSIONLESS_KEY = "__none";

const SIDE_LABELS: Record<RightPanelSide, string> = {
  timeline: "Timeline",
  artifacts: "Artifacts",
  comments: "Comments",
  changes: "Changes",
};

const SIDE_ORDER: readonly RightPanelSide[] = [
  "timeline",
  "artifacts",
  "comments",
  "changes",
];

function sideIcon(side: RightPanelSide, size: number): ReactNode {
  if (side === "timeline") return <PulseIcon size={size} />;
  if (side === "artifacts") return <PackageIcon size={size} />;
  if (side === "comments") return <ChatCircleIcon size={size} />;
  return <GitDiffIcon size={size} />;
}

/** The task the right panel talks about: the one on the current route. */
function useRightPanelTask(): Task | null {
  const params = useParams({ strict: false });
  const taskId = params.taskId ?? null;
  const { data: tasks } = useTasks();
  const fromList = taskId ? tasks?.find((t) => t.id === taskId) : undefined;
  // A session reached by deep link can be open before the list carries it.
  const { data: fetched } = useQuery({
    ...taskDetailQuery(taskId ?? ""),
    enabled: Boolean(taskId) && !fromList,
  });
  if (!taskId) return null;
  return fromList ?? fetched ?? null;
}

/** Which panel this session has open. */
function useActiveSide(taskId: string | null): RightPanelSide | null {
  const stored = useRightPanelStore(
    (s) => s.sideByKey[taskId ?? SESSIONLESS_KEY],
  );
  const reviewMode = useReviewNavigationStore((s) =>
    taskId ? (s.reviewModes[taskId] ?? "closed") : "closed",
  );
  return resolveRightPanelSide({
    stored,
    hasTask: taskId != null,
    isReviewOpen: reviewMode !== "closed",
  });
}

function openSide(side: RightPanelSide | null, taskId: string | null): void {
  const { setSideForKey } = useRightPanelStore.getState();
  const { setReviewMode } = useReviewNavigationStore.getState();
  setSideForKey(taskId ?? SESSIONLESS_KEY, side);
  if (!taskId) return;
  // Changes rides the review store so the command menu, PR links, and diff
  // toggles that already open review all land on the same panel, and so that
  // picking another panel closes what they opened.
  setReviewMode(taskId, side === "changes" ? "split" : "closed");
}

function toggleSide(
  side: RightPanelSide,
  active: RightPanelSide | null,
  taskId: string | null,
): void {
  openSide(active === side ? null : side, taskId);
}

/**
 * The panel's own switcher: one button per side, the active one toggling the
 * panel closed. It sits a row below the header band, pinned to the right edge,
 * and stays exactly there whether the panel is open or closed — the panel
 * slides out from under it.
 */
function RightPanelButtons({
  active,
  taskId,
}: {
  active: RightPanelSide | null;
  taskId: string | null;
}) {
  return (
    <TooltipProvider delay={400}>
      <div className="flex shrink-0 items-center gap-0.5">
        {SIDE_ORDER.map((side) => (
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
                  {sideIcon(side, 16)}
                </Button>
              }
            />
            <TooltipContent side="bottom">{SIDE_LABELS[side]}</TooltipContent>
          </Tooltip>
        ))}
      </div>
    </TooltipProvider>
  );
}

function ChangesPanelContent({ task }: { task: Task }) {
  const workspace = useWorkspace(task.id);
  const isCloud =
    workspace?.mode === "cloud" || task.latest_run?.environment === "cloud";
  return isCloud ? <CloudReviewPage task={task} /> : <ReviewPage task={task} />;
}

/**
 * A thread picked on the artifact itself is read in the Comments panel, so the
 * pick has to bring the panel with it. Only a fresh request opens it: a focus
 * left over from an earlier visit must not hijack the panel on mount.
 */
function useCommentFocusOpensPanel(taskId: string | null): void {
  const focusByTask = useCommentNavigationStore((state) => state.focusByTask);
  const acknowledgeCommentsTabOpen = useCommentNavigationStore(
    (state) => state.acknowledgeCommentsTabOpen,
  );
  const commentFocus = taskId ? focusByTask[taskId] : null;
  const seenFocus = useRef(
    new Map(
      Object.entries(focusByTask).map(([focusTaskId, focus]) => [
        focusTaskId,
        focus?.nonce ?? null,
      ]),
    ),
  );
  useEffect(() => {
    if (!taskId || !commentFocus?.openCommentsTab) return;
    if (commentFocus.nonce === seenFocus.current.get(taskId)) return;
    seenFocus.current.set(taskId, commentFocus.nonce);
    openSide("comments", taskId);
    acknowledgeCommentsTabOpen(taskId, commentFocus.nonce);
  }, [acknowledgeCommentsTabOpen, commentFocus, taskId]);
}

/**
 * The panel's title and contents fade with its slide, on the same curve the
 * width animates on, so the two read as one movement. The way out is quicker
 * than the way in, so the panel is already gone as the column finishes closing.
 */
const PANEL_FADE_OUT_MS = 120;

/**
 * The side to draw, which outlasts the one that is open: a closing panel has to
 * keep its title and contents on screen to fade them out, then drop them. A
 * drag that is still held keeps them, since dragging back out brings the same
 * panel in and rebuilding it mid-drag would stutter.
 */
function useFadingSide(
  active: RightPanelSide | null,
  held: boolean,
): RightPanelSide | null {
  const [drawn, setDrawn] = useState(active);
  useEffect(() => {
    if (active != null) {
      setDrawn(active);
      return;
    }
    if (held) return;
    const timer = setTimeout(() => setDrawn(null), PANEL_FADE_OUT_MS);
    return () => clearTimeout(timer);
  }, [active, held]);
  return drawn;
}

/**
 * The right panel column: a push column beside the content, one panel at a
 * time, shared resizable width. Its switcher is pinned to the top right of the
 * column and outlives any one panel, so the panel opens and closes beneath a
 * row of buttons that never move. Every side it shows belongs to a session, so
 * the whole column keeps to a session's own page.
 */
export function RightPanel() {
  const onSession = useParams({ strict: false }).taskId != null;
  const task = useRightPanelTask();
  const taskId = task?.id ?? null;
  const active = useActiveSide(taskId);
  useCommentFocusOpensPanel(taskId);

  const width = useRightPanelStore((s) => s.width);
  const setWidth = useRightPanelStore((s) => s.setWidth);
  const isResizing = useRightPanelStore((s) => s.isResizing);
  const setIsResizing = useRightPanelStore((s) => s.setIsResizing);

  const open = active != null;
  const drawn = useFadingSide(active, isResizing);

  // Dragging the handle past the panel's floor closes it, and dragging back out
  // while still holding brings it in again — so the side it went out on has to
  // outlive the close.
  const lastSideRef = useRef<RightPanelSide>(
    active ?? DEFAULT_RIGHT_PANEL_SIDE,
  );
  useEffect(() => {
    if (active != null) lastSideRef.current = active;
  }, [active]);

  if (!onSession) return null;

  return (
    <>
      <ResizableSidebar
        open={open}
        width={width}
        setWidth={setWidth}
        isResizing={isResizing}
        setIsResizing={setIsResizing}
        side="right"
        minWidth={RIGHT_PANEL_MIN_WIDTH}
        setOpen={(next) => openSide(next ? lastSideRef.current : null, taskId)}
      >
        <div
          className={cn(
            "flex h-full min-h-0 flex-col bg-background transition-opacity ease-out motion-reduce:transition-none",
            open ? "opacity-100 duration-200" : "opacity-0 duration-[120ms]",
          )}
        >
          {drawn && (
            <>
              {/* The right end of the row is the switcher's, so the title stops
                  short of it rather than running underneath. */}
              <div className="flex h-[32px] shrink-0 items-center border-border border-b pr-[108px] pl-3">
                <span className="min-w-0 truncate font-medium text-[13px]">
                  {SIDE_LABELS[drawn]}
                </span>
              </div>
              {/* Nothing under the title until the session resolves: the route
                  says there is one, so an empty state would be a lie. */}
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                {task &&
                  (drawn === "changes" ? (
                    <ChangesPanelContent task={task} />
                  ) : (
                    <ActivityPanelBody task={task} tab={drawn} canOpenInPlace />
                  ))}
              </div>
            </>
          )}
        </div>
      </ResizableSidebar>
      {/* Outside the sliding column, so the buttons hold their place while the
          panel comes and goes under them — above its closed layer, which parks
          itself at z-50 across this corner on the way out. */}
      <div className="absolute top-0 right-0 z-[60] flex h-[32px] items-center pr-2">
        <RightPanelButtons active={active} taskId={taskId} />
      </div>
    </>
  );
}
