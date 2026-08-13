import {
  ChatCircleIcon,
  GitDiffIcon,
  PackageIcon,
  PulseIcon,
  XIcon,
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
import { type ReactNode, useEffect, useRef } from "react";
import {
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
 * The always-there buttons in the header band. The panel opens beneath them;
 * one at a time, the active button toggles closed.
 */
export function RightPanelButtons() {
  const task = useRightPanelTask();
  const taskId = task?.id ?? null;
  const active = useActiveSide(taskId);

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

function SidePanelEmpty({ side }: { side: RightPanelSide }) {
  const description =
    side === "timeline"
      ? "Open a session to follow its activity."
      : side === "artifacts"
        ? "Open a session to see the artifacts it produced."
        : side === "comments"
          ? "Open a session to read and reply to its comments."
          : "Open a session to review its changes.";
  return (
    <Empty className="border-0 py-10">
      <EmptyHeader>
        <EmptyMedia variant="icon">{sideIcon(side, 18)}</EmptyMedia>
        <EmptyTitle>No session open</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
    </Empty>
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
 * The right panel column: a push column under the header-band buttons, one
 * panel at a time, shared resizable width.
 */
export function RightPanel() {
  const task = useRightPanelTask();
  const taskId = task?.id ?? null;
  const active = useActiveSide(taskId);
  useCommentFocusOpensPanel(taskId);

  const width = useRightPanelStore((s) => s.width);
  const setWidth = useRightPanelStore((s) => s.setWidth);
  const isResizing = useRightPanelStore((s) => s.isResizing);
  const setIsResizing = useRightPanelStore((s) => s.setIsResizing);

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
          <div className="flex h-[32px] shrink-0 items-center gap-1 border-border border-b pr-1 pl-3">
            <span className="font-medium text-[13px]">
              {SIDE_LABELS[active]}
            </span>
            <Button
              variant="default"
              size="icon-sm"
              aria-label={`Close ${SIDE_LABELS[active].toLowerCase()}`}
              className="ml-auto"
              onClick={() => openSide(null, taskId)}
            >
              <XIcon size={14} />
            </Button>
          </div>
        )}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {active === "changes" &&
            (task ? (
              <ChangesPanelContent task={task} />
            ) : (
              <SidePanelEmpty side="changes" />
            ))}
          {active != null &&
            active !== "changes" &&
            (task ? (
              <ActivityPanelBody task={task} tab={active} canOpenInPlace />
            ) : (
              <SidePanelEmpty side={active} />
            ))}
        </div>
      </div>
    </ResizableSidebar>
  );
}
