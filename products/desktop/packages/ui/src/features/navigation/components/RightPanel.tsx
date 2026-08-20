import {
  ArrowsInSimpleIcon,
  ArrowsOutSimpleIcon,
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
import { preloadReviewPages } from "@posthog/ui/features/code-review/components/preloadReviewPages";
import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import { PanelResizeHandle } from "@posthog/ui/features/navigation/components/PanelResizeHandle";
import {
  openRightPanelSide,
  SWITCHER_WIDTH_PX,
} from "@posthog/ui/features/navigation/rightPanelSide";
import { useCommentFocusRequest } from "@posthog/ui/features/sessions/useCommentFocusRequest";
import {
  useSessionArtifactCount,
  useSessionIsWorking,
} from "@posthog/ui/features/sessions/useSessionArtifactCount";
import { TIP_KEYS } from "@posthog/ui/features/settings/tipKeys";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { useIsCloudTask } from "@posthog/ui/features/workspace/useWorkspace";
import { TeachingTip } from "@posthog/ui/primitives/TeachingTip";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import {
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  DEFAULT_RIGHT_PANEL_SIDE,
  PANEL_PUSH_MAX_SHARE,
  PANEL_ROW_INSET_PX,
  type RightPanelSide,
  resolveArtifactMark,
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

/** The one lesson this switcher teaches: where a run's deliverables land. */
const ARTIFACTS_PANEL_TIP = TIP_KEYS.sessionArtifactsLocation;

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

/** One side's button: opens that panel, or closes it when it is the one open. */
function SideButton({
  side,
  active,
  taskId,
  marked = false,
}: {
  side: RightPanelSide;
  active: RightPanelSide | null;
  taskId: string;
  /** Something has arrived on this side that the panel hasn't shown yet. */
  marked?: boolean;
}) {
  const { label, Icon } = SIDES[side];
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="default"
            size="icon-sm"
            aria-label={marked ? `${label} (new)` : label}
            data-selected={active === side || undefined}
            onClick={() =>
              openRightPanelSide(active === side ? null : side, taskId)
            }
            className="relative text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
          >
            <Icon size={16} />
            {marked && (
              // Ringed in the row's own background so the dot still reads
              // where it overlaps the icon's strokes.
              <span
                aria-hidden
                className="absolute top-0.5 right-0.5 size-1.5 rounded-full bg-primary ring-2 ring-background"
              />
            )}
          </Button>
        }
      />
      <TooltipContent side="bottom">{label}</TooltipContent>
    </Tooltip>
  );
}

/**
 * The panel's own switcher: one button per side, the active one toggling the
 * panel closed. It keeps the same corner in both places it is drawn - the
 * panel's header row while the panel is open, and the content row's own top
 * right while it is away - so the buttons read as fixed.
 */
export function RightPanelButtons({
  active,
  taskId,
  hasNewArtifacts,
  offerArtifactsTip = false,
  artifactCount,
}: {
  active: RightPanelSide | null;
  taskId: string;
  /** Artifacts have arrived that this session's panel hasn't shown yet. */
  hasNewArtifacts: boolean;
  /** The turn that produced them has ended, so the tip can point at where they went. */
  offerArtifactsTip?: boolean;
  /** How many the session has, so each new one is a fresh chance to teach. */
  artifactCount?: number;
}) {
  return (
    <TooltipProvider delay={400}>
      <div className="pointer-events-auto flex shrink-0 items-center gap-0.5">
        {SIDE_ORDER.map((side) =>
          side === "artifacts" ? (
            <TeachingTip
              key={side}
              id={ARTIFACTS_PANEL_TIP}
              open={offerArtifactsTip}
              // The mark stays up until the panel is opened, so `open` can hold
              // across several runs. The count is what separates them, and it
              // is why asking for more artifacts offers the tip again.
              moment={artifactCount}
              message="New artifacts show up here"
            >
              <SideButton
                side={side}
                active={active}
                taskId={taskId}
                marked={hasNewArtifacts}
              />
            </TeachingTip>
          ) : (
            <SideButton
              key={side}
              side={side}
              active={active}
              taskId={taskId}
            />
          ),
        )}
      </div>
    </TooltipProvider>
  );
}

/**
 * Whether a session has artifacts its panel hasn't shown yet. The first count a
 * session reports is taken as seen, so a session opened long after its run
 * doesn't announce work the reader already knows about; from there the mark
 * clears whenever the panel is on Artifacts.
 */
function useNewArtifacts(
  taskId: string,
  task: Task | null,
  active: RightPanelSide | null,
): { hasNew: boolean; count: number } {
  const count = useSessionArtifactCount(task);
  // The count covers the latest run only, so the baseline is keyed per run too.
  // A resume run replaces `latest_run` with a fresh, smaller manifest; a
  // per-task baseline would then hold the old run's higher total and swallow the
  // new run's first deliverables until they passed it.
  const seenKey = `${taskId}:${task?.latest_run?.id ?? ""}`;
  const seen = useRightPanelStore((s) => s.seenArtifactCountByKey[seenKey]);
  const markArtifactsSeen = useRightPanelStore((s) => s.markArtifactsSeen);
  const { markSeen, hasNew } = resolveArtifactMark({
    count,
    seen,
    isShowingArtifacts: active === "artifacts",
    // The count reads zero until the task resolves and a manifest source lands.
    // Not ready yet means don't take that zero as the seen baseline.
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

/** The control that takes the panel between its own width and the whole row. */
function ExpandButton({
  expanded,
  onToggle,
}: {
  expanded: boolean;
  onToggle: () => void;
}) {
  const label = expanded ? "Collapse panel" : "Expand panel";
  return (
    <TooltipProvider delay={400}>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              variant="default"
              size="icon-sm"
              aria-label={label}
              onClick={onToggle}
              className="text-muted-foreground"
            >
              {expanded ? (
                <ArrowsInSimpleIcon size={16} />
              ) : (
                <ArrowsOutSimpleIcon size={16} />
              )}
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

/**
 * The panel's title row. It stops short of the corner the switcher floats over,
 * so the title and the expand control never run under buttons that outlive any
 * one panel.
 */
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

/** A panel's contents, the same whether it is docked or expanded. */
function PanelContent({
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
}

/**
 * How long the panel takes to slide in, widen, or go away.
 */
const SLIDE_MS = 200;

/**
 * The two layers the panel is drawn in. The spacer is what pushes the content
 * pane over, and it stops growing at its share of the row; the panel itself is
 * laid over the row's right edge at whatever width it has been given, so past
 * that point it widens across a pane that has already stopped reflowing.
 * Expanding is then only a wider panel over the same parked pane, not a
 * relayout of everything under it.
 *
 * Both layers belong to the content row, so the panel reaches the row's edges
 * and no further - the nav beside it stays uncovered.
 */
export function RightPanelSurface({
  panelRef,
  open,
  expanded,
  width,
  isResizing,
  children,
}: {
  panelRef: RefObject<HTMLDivElement | null>;
  open: boolean;
  /** Taking the whole row, rather than the width it was dragged to. */
  expanded: boolean;
  width: number;
  isResizing: boolean;
  children?: ReactNode;
}) {
  // A drag is the pointer's own movement, so the panel has to keep up with it
  // frame for frame rather than easing toward each width it is handed.
  const slide = isResizing ? "0ms" : `${SLIDE_MS}ms`;

  return (
    <>
      {/* Stops at the share of the row the panel is allowed to push, after
          which the pane stops moving and the panel carries on widening. */}
      <div
        className="h-full shrink-0 transition-[width] ease-out motion-reduce:transition-none"
        style={{
          width: open
            ? `min(${width}px, ${PANEL_PUSH_MAX_SHARE * 100}%)`
            : "0px",
          transitionDuration: slide,
        }}
      />
      <div
        ref={panelRef}
        className="absolute inset-y-0 right-0 z-40 flex min-w-0 flex-col border-gray-6 border-l bg-background transition-[width,transform] ease-out motion-reduce:transition-none"
        style={{
          width: expanded ? "100%" : `${width}px`,
          // One ceiling for both widths, so a width stored on a wider window
          // lands where expanding would, rather than over the nav.
          maxWidth: `calc(100% - ${PANEL_ROW_INSET_PX}px)`,
          transform: open ? "translateX(0)" : "translateX(100%)",
          pointerEvents: open ? undefined : "none",
          transitionDuration: slide,
        }}
      >
        {children}
      </div>
    </>
  );
}

/**
 * The side to draw, which outlasts the one that is open: a closing panel has to
 * keep its title and contents on screen to slide them out, then drop them. A
 * drag that is still held keeps them, since dragging back out brings the same
 * panel in and rebuilding it mid-drag would stutter.
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
 * The right panel: one panel at a time at the right of the content row, with a
 * switcher that outlives any one of them.
 */
function SessionRightPanel({ taskId }: { taskId: string }) {
  const task = useRightPanelTask(taskId);
  const active = useActiveSide(taskId);
  const { hasNew: hasNewArtifacts, count: artifactCount } = useNewArtifacts(
    taskId,
    task,
    active,
  );
  // Only once the agent has stopped: a tip that lands mid-turn points at a
  // list that is still filling.
  const isWorking = useSessionIsWorking(task);
  useCommentFocusRequest(taskId, () => openRightPanelSide("comments", taskId));

  const width = useRightPanelStore((s) => s.width);
  const setWidth = useRightPanelStore((s) => s.setWidth);
  const isResizing = useRightPanelStore((s) => s.isResizing);
  const setIsResizing = useRightPanelStore((s) => s.setIsResizing);
  const setExpandedForKey = useRightPanelStore((s) => s.setExpandedForKey);
  const wantsExpanded = useRightPanelStore(
    (s) => s.expandedByKey[taskId] ?? false,
  );

  const panelRef = useRef<HTMLDivElement>(null);
  const open = active != null;
  // A closed panel has nothing to expand, so the whole row waits for it to open
  // again rather than dropping the mode the reader chose.
  const expanded = open && wantsExpanded;
  const drawn = useDrawnSide(active, isResizing);

  useEffect(() => preloadReviewPages(), []);

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
      <RightPanelSurface
        panelRef={panelRef}
        open={open}
        expanded={expanded}
        width={width}
        isResizing={isResizing}
      >
        {drawn && (
          <>
            <PanelHeader
              title={
                <span className={PANEL_TITLE_CLASS}>{SIDES[drawn].label}</span>
              }
            >
              <ExpandButton
                expanded={expanded}
                onToggle={() => setExpandedForKey(taskId, !expanded)}
              />
            </PanelHeader>
            <PanelContent task={task} side={drawn} />
            <PanelResizeHandle
              panelRef={panelRef}
              open={open}
              expanded={expanded}
              width={width}
              isResizing={isResizing}
              setIsResizing={setIsResizing}
              setWidth={setWidth}
              setOpen={setOpen}
              setExpanded={(next) => setExpandedForKey(taskId, next)}
            />
          </>
        )}
      </RightPanelSurface>
      {/* Outside the panel, so the buttons hold their place while it comes and
          goes under them. It has to outrank the panel's own layer; the row's
          `isolate` keeps that rank from reaching the app's overlays. */}
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
