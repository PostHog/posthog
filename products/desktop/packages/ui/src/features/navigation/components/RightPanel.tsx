import { ArrowsHorizontalIcon } from "@phosphor-icons/react";
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
import { preloadReviewPages } from "@posthog/ui/features/code-review/components/preloadReviewPages";
import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import { PanelResizeHandle } from "@posthog/ui/features/navigation/components/PanelResizeHandle";
import { RightPanelButtons } from "@posthog/ui/features/navigation/components/RightPanelButtons";
import {
  RightPanelSurface,
  SLIDE_MS,
} from "@posthog/ui/features/navigation/components/RightPanelSurface";
import { resolvePanelGeometry } from "@posthog/ui/features/navigation/rightPanelGeometry";
import {
  openRightPanelSide,
  SIDES,
  SWITCHER_WIDTH_PX,
} from "@posthog/ui/features/navigation/rightPanelSide";
import { useActiveSession } from "@posthog/ui/features/navigation/useActiveSession";
import { useCommentFocusRequest } from "@posthog/ui/features/sessions/useCommentFocusRequest";
import {
  useSessionArtifactCount,
  useSessionIsWorking,
} from "@posthog/ui/features/sessions/useSessionArtifactCount";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useIsCloudTask } from "@posthog/ui/features/workspace/useWorkspace";
import { useParentWidth } from "@posthog/ui/primitives/hooks/useObservedWidth";
import { useQuery } from "@tanstack/react-query";
import {
  memo,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  type RightPanelSide,
  resolveArtifactMark,
  resolveRightPanelSide,
  useRightPanelStore,
} from "../rightPanelStore";

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
  const closedByDefault = useRightPanelStore((s) => s.closedByDefault);
  const reviewMode = useReviewNavigationStore(
    (s) => s.reviewModes[taskId] ?? "closed",
  );
  return resolveRightPanelSide({
    stored,
    closedByDefault,
    isReviewOpen: reviewMode !== "closed",
  });
}

/** Artifacts a session's panel hasn't shown yet. */
function useNewArtifacts(
  taskId: string,
  task: Task | null,
  active: RightPanelSide | null,
): { hasNew: boolean; count: number } {
  const count = useSessionArtifactCount(task);
  // Keyed per run: a resume replaces `latest_run` with a smaller manifest, and a
  // per-task baseline would swallow the new run's first deliverables.
  const seenKey = `${taskId}:${task?.latest_run?.id ?? ""}`;
  const seen = useRightPanelStore((s) => s.seenArtifactCountByKey[seenKey]);
  const markArtifactsSeen = useRightPanelStore((s) => s.markArtifactsSeen);
  const { markSeen, hasNew } = resolveArtifactMark({
    count,
    seen,
    isShowingArtifacts: active === "artifacts",
    // The count reads zero until a manifest lands; don't bank that as seen.
    ready: task !== null,
  });

  useEffect(() => {
    if (markSeen) markArtifactsSeen(seenKey, count);
  }, [count, markArtifactsSeen, markSeen, seenKey]);

  return { hasNew, count };
}

function ChangesPanelContent({ task }: { task: Task }) {
  return useIsCloudTask(task) ? (
    <CloudReviewPage task={task} />
  ) : (
    <ReviewPage task={task} />
  );
}

/**
 * Takes the panel out to the whole row and back. Active at full width however
 * the panel got there - a drag to the far edge lands where the button does.
 */
function ExpandButton({
  active,
  onToggle,
}: {
  active: boolean;
  onToggle: () => void;
}) {
  const label = active ? "Shrink panel" : "Expand panel";
  return (
    <TooltipProvider delay={400}>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="default"
              size="icon-sm"
              aria-label={label}
              data-selected={active || undefined}
              onClick={onToggle}
              className="text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
            >
              <ArrowsHorizontalIcon size={16} />
            </Button>
          }
        />
        <TooltipContent side="bottom">{label}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/** What the panel's title reads like. */
const PANEL_TITLE_CLASS = "min-w-0 flex-1 truncate font-medium text-[13px]";

/** Stops short of the corner the switcher floats over. */
function PanelHeader({
  title,
  children,
}: {
  title: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div
      className="flex h-[32px] shrink-0 items-center gap-0.5 border-border border-b pl-3"
      style={{ paddingRight: SWITCHER_WIDTH_PX }}
    >
      {title}
      {children}
    </div>
  );
}

/**
 * Memoized: the row's width is observed a level up, and without this every tick
 * of that observer would re-render a mounted review page.
 */
const PanelContent = memo(function PanelContent({
  task,
  side,
}: {
  task: Task | null;
  side: RightPanelSide;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {task &&
        (side === "changes" ? (
          <ChangesPanelContent task={task} />
        ) : (
          <ActivityPanelBody task={task} tab={side} canOpenInPlace />
        ))}
    </div>
  );
});

/**
 * The side to draw, which outlasts the one that is open: a closing panel needs
 * its contents on screen to slide them out. A held drag keeps them, since
 * dragging back out brings the same panel in.
 */
function useDrawnSide(
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
    const timer = setTimeout(() => setDrawn(null), SLIDE_MS);
    return () => clearTimeout(timer);
  }, [active, held]);

  return drawn;
}

/** Every side belongs to a session, so nothing below this runs elsewhere. */
export function RightPanel() {
  const { taskId } = useActiveSession();
  // Keyed by session: carrying per-session state across a navigation draws the
  // previous session's panel over the new one for a frame.
  return taskId ? <SessionRightPanel key={taskId} taskId={taskId} /> : null;
}

/** One panel at a time, under a switcher that outlives any one of them. */
function SessionRightPanel({ taskId }: { taskId: string }) {
  const task = useRightPanelTask(taskId);
  const active = useActiveSide(taskId);
  const { hasNew: hasNewArtifacts, count: artifactCount } = useNewArtifacts(
    taskId,
    task,
    active,
  );
  // A tip that lands mid-turn points at a list that is still filling.
  const isWorking = useSessionIsWorking(task);
  useCommentFocusRequest(taskId, () => openRightPanelSide("comments", taskId));

  const width = useRightPanelStore((s) => s.width);
  const setWidth = useRightPanelStore((s) => s.setWidth);
  const isResizing = useRightPanelStore((s) => s.isResizing);
  const setExpandedForKey = useRightPanelStore((s) => s.setExpandedForKey);
  const wantsExpanded = useRightPanelStore(
    (s) => s.expandedByKey[taskId] ?? false,
  );

  const panelRef = useRef<HTMLDivElement>(null);
  const rowWidth = useParentWidth(panelRef);
  const open = active != null;
  // A closed panel has nothing to expand, so the row waits for it to open again.
  const expanded = open && wantsExpanded;
  const drawn = useDrawnSide(active, isResizing);

  const geometry = resolvePanelGeometry({
    storedWidth: width,
    rowWidth,
    open,
    expanded,
  });
  const uncover = useCallback(() => {
    setExpandedForKey(taskId, false);
    setWidth(geometry.uncoveredWidth);
  }, [geometry.uncoveredWidth, setExpandedForKey, setWidth, taskId]);

  useEffect(() => preloadReviewPages(), []);

  return (
    <>
      <RightPanelSurface
        panelRef={panelRef}
        open={open}
        expanded={expanded}
        width={width}
        geometry={geometry}
        isResizing={isResizing}
        onUncover={uncover}
      >
        {drawn && (
          <>
            <PanelHeader
              title={
                <span className={PANEL_TITLE_CLASS}>{SIDES[drawn].label}</span>
              }
            >
              <ExpandButton
                active={geometry.atFullWidth}
                onToggle={() =>
                  geometry.atFullWidth
                    ? uncover()
                    : setExpandedForKey(taskId, true)
                }
              />
            </PanelHeader>
            <PanelContent task={task} side={drawn} />
            <PanelResizeHandle
              taskId={taskId}
              panelRef={panelRef}
              rowWidth={rowWidth}
            />
          </>
        )}
      </RightPanelSurface>
      {/* Outside the panel, so the buttons hold their place while it slides.
          The row's `isolate` keeps this rank off the app's overlays. */}
      <div
        className="pointer-events-none absolute top-0 right-0 z-60 flex h-[32px] items-center justify-end pr-2"
        style={{ width: SWITCHER_WIDTH_PX }}
      >
        <RightPanelButtons
          active={active}
          taskId={taskId}
          hasNewArtifacts={hasNewArtifacts}
          offerArtifactsTip={hasNewArtifacts && !isWorking}
          artifactCount={artifactCount}
        />
      </div>
    </>
  );
}
