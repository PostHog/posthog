import {
  ChatCircleIcon,
  GitDiffIcon,
  type Icon,
  PackageIcon,
  PulseIcon,
} from "@phosphor-icons/react";
import {
  Button,
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
import { openRightPanelSide } from "@posthog/ui/features/navigation/rightPanelSide";
import { useCommentFocusRequest } from "@posthog/ui/features/sessions/useCommentFocusRequest";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useIsCloudTask } from "@posthog/ui/features/workspace/useWorkspace";
import {
  ResizableSidebar,
  SLIDE_MS,
} from "@posthog/ui/primitives/ResizableSidebar";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";
import {
  DEFAULT_RIGHT_PANEL_SIDE,
  RIGHT_PANEL_MIN_WIDTH,
  type RightPanelSide,
  resolveRightPanelSide,
  useRightPanelStore,
} from "../rightPanelStore";

const SIDES: Record<RightPanelSide, { label: string; Icon: Icon }> = {
  timeline: { label: "Timeline", Icon: PulseIcon },
  artifacts: { label: "Artifacts", Icon: PackageIcon },
  comments: { label: "Comments", Icon: ChatCircleIcon },
  changes: { label: "Changes", Icon: GitDiffIcon },
};

const SIDE_ORDER: readonly RightPanelSide[] = [
  "timeline",
  "artifacts",
  "comments",
  "changes",
];

/**
 * The room the switcher takes at the right of the row, covering SIDE_ORDER at
 * icon-sm. The panel's header row leaves it free for the title, and while the
 * panel is closed the content pane's own chrome (the tab strip and its split
 * and close controls) keeps out of it through CONTENT_CHROME_RIGHT_VAR.
 */
export const SWITCHER_WIDTH_PX = 112;

/** The task the right panel talks about: the one on the current route. */
function useRightPanelTask(taskId: string): Task | null {
  const { data: tasks } = useTasks();
  const fromList = tasks?.find((t) => t.id === taskId);
  // A session reached by deep link can be open before the list carries it.
  const { data: fetched } = useQuery({
    ...taskDetailQuery(taskId),
    enabled: !fromList,
  });
  return fromList ?? fetched ?? null;
}

/** Which panel this session has open. */
function useActiveSide(taskId: string): RightPanelSide | null {
  const stored = useRightPanelStore((s) => s.sideByKey[taskId]);
  const reviewMode = useReviewNavigationStore(
    (s) => s.reviewModes[taskId] ?? "closed",
  );
  return resolveRightPanelSide({
    stored,
    isReviewOpen: reviewMode !== "closed",
  });
}

/**
 * The panel's own switcher: one button per side, the active one toggling the
 * panel closed. It sits a row below the header band, pinned to the right edge,
 * and stays there whether the panel is open or closed, because the panel slides
 * out from under it.
 */
function RightPanelButtons({
  active,
  taskId,
}: {
  active: RightPanelSide | null;
  taskId: string;
}) {
  return (
    <TooltipProvider delay={400}>
      <div className="pointer-events-auto flex shrink-0 items-center gap-0.5">
        {SIDE_ORDER.map((side) => {
          const { label, Icon } = SIDES[side];
          return (
            <Tooltip key={side}>
              <TooltipTrigger
                render={
                  <Button
                    variant="default"
                    size="icon-sm"
                    aria-label={label}
                    data-selected={active === side || undefined}
                    onClick={() =>
                      openRightPanelSide(active === side ? null : side, taskId)
                    }
                    className="text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
                  >
                    <Icon size={16} />
                  </Button>
                }
              />
              <TooltipContent side="bottom">{label}</TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}

function ChangesPanelContent({ task }: { task: Task }) {
  return useIsCloudTask(task) ? (
    <CloudReviewPage task={task} />
  ) : (
    <ReviewPage task={task} />
  );
}

/**
 * The panel's title and contents fade with its slide, so the two read as one
 * movement: in over the slide's own duration, out quicker, so the panel is
 * already gone as the column finishes closing.
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
 * Every side the panel shows belongs to a session, so the column keeps to a
 * session's own page and nothing below this runs anywhere else.
 */
export function RightPanel() {
  const taskId = useParams({ strict: false }).taskId;
  // Keyed by session: the panel holds per-session state (which side is drawn,
  // which comment request it has taken), and carrying that across a navigation
  // draws the previous session's panel over the new one for a frame.
  return taskId ? <SessionRightPanel key={taskId} taskId={taskId} /> : null;
}

/**
 * The right panel column: a push column beside the content, one panel at a
 * time, shared resizable width. Its switcher is pinned to the top right of the
 * column and outlives any one panel, so the panel opens and closes beneath a
 * row of buttons that never move.
 */
function SessionRightPanel({ taskId }: { taskId: string }) {
  const task = useRightPanelTask(taskId);
  const active = useActiveSide(taskId);
  useCommentFocusRequest(taskId, () => openRightPanelSide("comments", taskId));

  const width = useRightPanelStore((s) => s.width);
  const setWidth = useRightPanelStore((s) => s.setWidth);
  const isResizing = useRightPanelStore((s) => s.isResizing);
  const setIsResizing = useRightPanelStore((s) => s.setIsResizing);

  const open = active != null;
  const drawn = useFadingSide(active, isResizing);

  // Dragging the handle past the panel's floor closes it, and dragging back out
  // while still holding brings it in again. The drag holds the closing panel's
  // contents, so `drawn` is the side to put back; the fallback only stands in
  // for a reopen that starts from no panel at all.
  const setOpen = useCallback(
    (next: boolean) =>
      openRightPanelSide(
        next ? (drawn ?? DEFAULT_RIGHT_PANEL_SIDE) : null,
        taskId,
      ),
    [drawn, taskId],
  );

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
        setOpen={setOpen}
      >
        <div
          className="flex h-full min-h-0 flex-col bg-background transition-opacity ease-out motion-reduce:transition-none"
          style={{
            opacity: open ? 1 : 0,
            transitionDuration: open
              ? `${SLIDE_MS}ms`
              : `${PANEL_FADE_OUT_MS}ms`,
          }}
        >
          {drawn && (
            <>
              <div
                className="flex h-[32px] shrink-0 items-center border-border border-b pl-3"
                style={{ paddingRight: SWITCHER_WIDTH_PX }}
              >
                <span className="min-w-0 truncate font-medium text-[13px]">
                  {SIDES[drawn].label}
                </span>
              </div>
              {/* Nothing under the title until the session resolves, because
                  the route says there is a session and an empty state would
                  contradict it. */}
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
          panel comes and goes under them. It has to outrank the panel's closed
          layer, which sweeps across this corner at z-50 on the way out; the
          row's own `isolate` keeps that rank from reaching the app's overlays. */}
      <div
        className="pointer-events-none absolute top-0 right-0 z-60 flex h-[32px] items-center justify-end pr-2"
        style={{ width: SWITCHER_WIDTH_PX }}
      >
        <RightPanelButtons active={active} taskId={taskId} />
      </div>
    </>
  );
}
