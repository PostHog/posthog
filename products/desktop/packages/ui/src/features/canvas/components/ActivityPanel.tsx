import {
  ArrowDownIcon,
  ArrowSquareOutIcon,
  CaretRightIcon,
  XIcon,
} from "@phosphor-icons/react";
import { Button, Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { ActivityTimeline } from "@posthog/ui/features/canvas/components/ActivityTimeline";
import { ActivityLoadingState } from "@posthog/ui/features/canvas/components/activityRows";
import { TaskCard } from "@posthog/ui/features/canvas/components/ChannelFeedView";
import { TaskArtifactsList } from "@posthog/ui/features/canvas/components/TaskArtifactsList";
import { TaskCommentsList } from "@posthog/ui/features/canvas/components/TaskCommentsList";
import {
  AgentStatusLine,
  ThreadLoadingState,
} from "@posthog/ui/features/canvas/components/ThreadPanel";
import { useTaskCommentActivity } from "@posthog/ui/features/canvas/hooks/useTaskCommentActivity";
import { useTaskRuns } from "@posthog/ui/features/canvas/hooks/useTaskRuns";
import { useThreadConversation } from "@posthog/ui/features/canvas/hooks/useThreadConversation";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { buildConversationItems } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { useCommentsEnabled } from "@posthog/ui/features/sessions/useCommentsEnabled";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { track } from "@posthog/ui/shell/analytics";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type ActivityTab = "timeline" | "artifacts" | "comments";

const ACTIVITY_TABS: readonly { key: ActivityTab; label: string }[] = [
  { key: "timeline", label: "Timeline" },
  { key: "artifacts", label: "Artifacts" },
  { key: "comments", label: "Comments" },
] as const;

/** The 32px row this panel leads with: the tabs are the header, so the strip
 *  lines up with the tab bar of the pane on its left (TabbedPanel) and the
 *  review toolbar, which are the same fixed height and border. */
function ActivityHeader({
  tab,
  commentsEnabled,
  onTabChange,
  onClose,
  onToggleCollapsed,
  onOpenFull,
}: {
  tab: ActivityTab;
  commentsEnabled: boolean;
  onTabChange: (tab: ActivityTab) => void;
  onClose?: () => void;
  onToggleCollapsed?: () => void;
  onOpenFull?: () => void;
}) {
  return (
    <div className="flex h-[32px] shrink-0 items-center gap-1 border-b border-b-(--gray-6) pr-1 pl-2">
      <Tabs
        value={tab}
        onValueChange={(value: string) => onTabChange(value as ActivityTab)}
      >
        {/* Nothing spells out "Activity" any more, so the strip carries the name.
            The list fills the row's 32px and drops quill's 3px inset so the
            line-variant indicator (bottom: 0 of the list) lands on the row's
            bottom border, the way the left pane's tabs underline does. */}
        <TabsList
          variant="line"
          aria-label="Activity"
          className="h-[31px] gap-0.5 p-0"
        >
          {ACTIVITY_TABS.filter(
            (candidate) => commentsEnabled || candidate.key !== "comments",
          ).map((t) => (
            <TabsTrigger key={t.key} value={t.key} className="px-2.5">
              <span className="font-medium text-[13px]">{t.label}</span>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className="ml-auto flex shrink-0 items-center gap-1">
        {onOpenFull && (
          <Button
            variant="default"
            size="icon-sm"
            aria-label="Open full task"
            onClick={onOpenFull}
          >
            <ArrowSquareOutIcon size={14} />
          </Button>
        )}
        {onToggleCollapsed && (
          <Button
            variant="default"
            size="icon-sm"
            aria-label="Collapse activity"
            onClick={onToggleCollapsed}
          >
            <CaretRightIcon size={14} />
          </Button>
        )}
        {onClose && (
          <Button
            variant="default"
            size="icon-sm"
            aria-label="Close activity"
            onClick={onClose}
          >
            <XIcon size={14} />
          </Button>
        )}
      </div>
    </div>
  );
}

function ActivityConversation({
  task,
  channelId,
  onClose,
  onToggleCollapsed,
  onOpenFull,
  showTaskSummary,
  canOpenInPlace,
}: {
  task: Task;
  channelId: string;
  onClose?: () => void;
  onToggleCollapsed?: () => void;
  onOpenFull?: () => void;
  showTaskSummary: boolean;
  canOpenInPlace?: boolean;
}) {
  const taskId = task.id;
  const commentsEnabled = useCommentsEnabled();
  const {
    timeline,
    agentStatus,
    events,
    isPromptPending,
    hasLoadedThread,
    currentUser,
  } = useThreadConversation(task, { surface: "activity_panel" });

  const [tab, setTab] = useState<ActivityTab>("timeline");
  const handleTabChange = useCallback(
    (next: ActivityTab) => {
      setTab(next);
      track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
        action_type: "activity_tab_change",
        surface: "activity_panel",
        task_id: taskId,
        tab: next,
      });
    },
    [taskId],
  );

  // The comment feed is its own request, and only for the tab that draws it.
  const { threads: commentThreads, hasLoaded: hasLoadedComments } =
    useTaskCommentActivity(taskId, {
      enabled: commentsEnabled && tab === "timeline",
    });
  // Draw the timeline once both of its durable sources have answered, and never take it
  // away again. Gating on the live session instead (`isReady`) is what made the panel show
  // rows, blink a loader while the session connected, then show the rows again.
  const hasDrawnTimeline = useRef(false);
  const timelineReady =
    hasDrawnTimeline.current || (hasLoadedThread && hasLoadedComments);
  if (timelineReady) hasDrawnTimeline.current = true;
  const { runs } = useTaskRuns(taskId);

  const conversationItems = useMemo(
    () =>
      tab === "timeline"
        ? buildConversationItems(events, isPromptPending).items
        : [],
    [tab, events, isPromptPending],
  );

  // A thread picked on the artifact itself lives in the Comments tab, so the
  // pick has to bring the tab with it. Only a fresh request switches tabs: a
  // focus left over from an earlier visit must not hijack the panel on mount.
  const focusByTask = useCommentNavigationStore((state) => state.focusByTask);
  const commentFocus = focusByTask[taskId];
  const acknowledgeCommentsTabOpen = useCommentNavigationStore(
    (state) => state.acknowledgeCommentsTabOpen,
  );
  // Seed requests that predate this panel, but leave later requests for other
  // tasks pending until the reused panel switches to that task.
  const seenFocus = useRef(
    new Map(
      Object.entries(focusByTask).map(([focusTaskId, focus]) => [
        focusTaskId,
        focus?.nonce ?? null,
      ]),
    ),
  );
  useEffect(() => {
    if (
      commentsEnabled &&
      commentFocus?.openCommentsTab &&
      commentFocus.nonce !== seenFocus.current.get(taskId)
    ) {
      seenFocus.current.set(taskId, commentFocus.nonce);
      // Not handleTabChange: a programmatic switch isn't a user tab change.
      setTab("comments");
    }
  }, [commentFocus, commentsEnabled, taskId]);
  useEffect(() => {
    if (!commentsEnabled && tab === "comments") setTab("timeline");
  }, [commentsEnabled, tab]);
  useEffect(() => {
    if (tab === "comments" && commentFocus?.openCommentsTab) {
      acknowledgeCommentsTabOpen(taskId, commentFocus.nonce);
    }
  }, [acknowledgeCommentsTabOpen, commentFocus, tab, taskId]);

  const scrollRef = useRef<HTMLDivElement>(null);
  // Within this much of the bottom still counts as "watching the end", so a row arriving
  // mid-poll keeps following. Wide enough to survive a partially scrolled last row.
  const AT_BOTTOM_SLACK_PX = 48;
  const [hasNewerBelow, setHasNewerBelow] = useState(false);
  const scrollToLatest = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTo({ top: node.scrollHeight });
    setHasNewerBelow(false);
  }, []);
  const onScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    const atBottom =
      node.scrollHeight - node.scrollTop - node.clientHeight <=
      AT_BOTTOM_SLACK_PX;
    if (atBottom) setHasNewerBelow(false);
  }, []);
  // biome-ignore lint/correctness/useExhaustiveDependencies: follow the end when rendered content changes
  useEffect(() => {
    // Only the timeline reads bottom-up; the other tabs put what matters on top.
    if (tab !== "timeline") return;
    const node = scrollRef.current;
    if (!node) return;
    // Poll after poll, this ran on every refetch and yanked the panel to the bottom while
    // someone was reading further up. Follow the end only for a reader already at it, and
    // offer the jump to everyone else.
    const atBottom =
      node.scrollHeight - node.scrollTop - node.clientHeight <=
      AT_BOTTOM_SLACK_PX;
    if (atBottom) {
      node.scrollTo({ top: node.scrollHeight });
      setHasNewerBelow(false);
      return;
    }
    setHasNewerBelow(true);
  }, [timeline, events.length, agentStatus?.phase, tab]);

  const body = () => {
    if (tab === "comments") {
      return <TaskCommentsList task={task} timeline={timeline} />;
    }
    if (tab === "artifacts") {
      return (
        <TaskArtifactsList
          task={task}
          timeline={timeline}
          canOpenInPlace={canOpenInPlace}
        />
      );
    }
    if (!timelineReady) return <ActivityLoadingState />;
    return (
      <ActivityTimeline
        task={task}
        timeline={timeline}
        conversationItems={conversationItems}
        commentThreads={commentThreads}
        commentsEnabled={commentsEnabled}
        runCount={runs.length}
        currentUserId={currentUser?.id}
        canOpenInPlace={canOpenInPlace}
      />
    );
  };

  return (
    <div className="flex h-full min-w-0 flex-col bg-gray-1">
      <ActivityHeader
        tab={tab}
        commentsEnabled={commentsEnabled}
        onTabChange={handleTabChange}
        onOpenFull={onOpenFull}
        onToggleCollapsed={onToggleCollapsed}
        onClose={onClose}
      />

      {showTaskSummary && (
        <div className="z-10 px-2">
          <TaskCard task={task} channelId={channelId} inThread />
        </div>
      )}
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          aria-busy={!timelineReady}
          className="flex-1 overflow-y-auto"
        >
          {body()}
        </div>
        {tab === "timeline" && hasNewerBelow && (
          <Button
            variant="default"
            size="sm"
            className="-translate-x-1/2 absolute bottom-2 left-1/2 z-20 shadow-md"
            onClick={scrollToLatest}
          >
            <ArrowDownIcon size={12} />
            New activity
          </Button>
        )}
      </div>

      {tab === "timeline" && agentStatus && (
        <AgentStatusLine status={agentStatus} />
      )}
    </div>
  );
}

export function ActivityPanel({
  taskId,
  channelId,
  task: taskProp,
  onClose,
  collapsed,
  onToggleCollapsed,
  onOpenFull,
  showTaskSummary = true,
  canOpenInPlace,
}: {
  taskId: string;
  channelId: string;
  task?: Task;
  onClose?: () => void;
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  onOpenFull?: () => void;
  showTaskSummary?: boolean;
  canOpenInPlace?: boolean;
}) {
  const { data: fetchedTask } = useQuery({
    ...taskDetailQuery(taskId),
    enabled: !taskProp && !collapsed,
  });
  const task = taskProp ?? fetchedTask;

  if (collapsed) {
    return (
      <div className="flex h-full w-9 flex-col items-center border-border border-l bg-gray-1">
        {/* Same 32px band as the expanded header, so the button doesn't jump. */}
        <div className="flex h-[32px] shrink-0 items-center">
          <Button
            variant="default"
            size="icon-sm"
            aria-label="Expand activity"
            onClick={onToggleCollapsed}
          >
            <CaretRightIcon size={14} className="rotate-180" />
          </Button>
        </div>
      </div>
    );
  }

  if (!task) {
    return <ThreadLoadingState />;
  }

  return (
    <ActivityConversation
      task={task}
      channelId={channelId}
      onClose={onClose}
      onToggleCollapsed={onToggleCollapsed}
      onOpenFull={onOpenFull}
      showTaskSummary={showTaskSummary}
      canOpenInPlace={canOpenInPlace}
    />
  );
}
