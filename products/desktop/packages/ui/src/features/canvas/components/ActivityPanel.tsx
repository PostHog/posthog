import {
  ArrowSquareOutIcon,
  CaretRightIcon,
  XIcon,
} from "@phosphor-icons/react";
import { Button, Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { ActivityTimeline } from "@posthog/ui/features/canvas/components/ActivityTimeline";
import { TaskCard } from "@posthog/ui/features/canvas/components/ChannelFeedView";
import { TaskArtifactsList } from "@posthog/ui/features/canvas/components/TaskArtifactsList";
import { TaskCommentsList } from "@posthog/ui/features/canvas/components/TaskCommentsList";
import {
  AgentStatusLine,
  ThreadLoadingState,
  ThreadReplyComposer,
} from "@posthog/ui/features/canvas/components/ThreadPanel";
import { useThreadConversation } from "@posthog/ui/features/canvas/hooks/useThreadConversation";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { buildConversationItems } from "@posthog/ui/features/sessions/components/buildConversationItems";
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
  onTabChange,
  onClose,
  onToggleCollapsed,
  onOpenFull,
}: {
  tab: ActivityTab;
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
          {ACTIVITY_TABS.map((t) => (
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
  const {
    timeline,
    agentStatus,
    events,
    isPromptPending,
    isReady,
    members,
    currentUser,
    isTaskAuthor,
    canForward,
    draft,
    setDraft,
    isSubmitDisabled,
    submit,
    sendMessageToAgent,
    deleteMessage,
    onMentionInsert,
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
  const commentFocus = useCommentNavigationStore(
    (state) => state.focusByTask[taskId],
  );
  // Tracks the task too: this panel is reused across tasks without remounting,
  // so a nonce seen for the previous task says nothing about this one.
  const seenFocus = useRef({ taskId, nonce: commentFocus?.nonce });
  // Adjust during render rather than in an effect, so the panel never commits a
  // stale tab before switching. A new task resets the baseline (an old focus
  // must not hijack it); a fresh focus nonce for this task brings the Comments
  // tab with the pick.
  if (seenFocus.current.taskId !== taskId) {
    seenFocus.current = { taskId, nonce: commentFocus?.nonce };
  } else if (commentFocus && commentFocus.nonce !== seenFocus.current.nonce) {
    seenFocus.current = { taskId, nonce: commentFocus.nonce };
    // Not handleTabChange: a programmatic switch isn't a user tab change.
    setTab("comments");
  }

  const scrollRef = useRef<HTMLDivElement>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll when rendered thread content changes
  useEffect(() => {
    // Only the timeline reads bottom-up; the other tabs put what matters on top.
    if (tab !== "timeline") return;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [timeline, events.length, agentStatus?.phase, tab]);

  const showComposer = tab === "timeline";

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
    if (!isReady) return <ThreadLoadingState />;
    return (
      <ActivityTimeline
        task={task}
        timeline={timeline}
        conversationItems={conversationItems}
        currentUserUuid={currentUser?.uuid}
        currentUserEmail={currentUser?.email}
        isTaskAuthor={isTaskAuthor}
        canForward={canForward}
        canOpenInPlace={canOpenInPlace}
        onSendToAgent={sendMessageToAgent}
        onDelete={deleteMessage}
      />
    );
  };

  return (
    <div className="flex h-full min-w-0 flex-col bg-gray-1">
      <ActivityHeader
        tab={tab}
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
      <div
        ref={scrollRef}
        aria-busy={!isReady}
        className="flex-1 overflow-y-auto"
      >
        {body()}
      </div>

      {showComposer && agentStatus && <AgentStatusLine status={agentStatus} />}

      {showComposer && (
        <ThreadReplyComposer
          draft={draft}
          onDraftChange={setDraft}
          onSubmit={submit}
          members={members}
          allowAgentMention={isTaskAuthor && canForward}
          onMentionInsert={onMentionInsert}
          disabled={isSubmitDisabled}
        />
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
