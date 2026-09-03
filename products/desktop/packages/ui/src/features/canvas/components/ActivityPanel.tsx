import {
  ArrowSquareOutIcon,
  CaretRightIcon,
  XIcon,
} from "@phosphor-icons/react";
import { Button, Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import {
  ActivityPanelBody,
  type ActivityTab,
} from "@posthog/ui/features/canvas/components/ActivityPanelBody";
import { TaskSummaryRow } from "@posthog/ui/features/canvas/components/ChannelFeedView";
import { ThreadLoadingState } from "@posthog/ui/features/canvas/components/ThreadPanel";
import { useTaskThread } from "@posthog/ui/features/canvas/hooks/useTaskThread";
import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { useCommentFocusRequest } from "@posthog/ui/features/sessions/useCommentFocusRequest";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { track } from "@posthog/ui/shell/analytics";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

const ACTIVITY_TABS: readonly { key: ActivityTab; label: string }[] = [
  { key: "timeline", label: "Timeline" },
  { key: "artifacts", label: "Artifacts" },
  { key: "comments", label: "Comments" },
] as const;

/** The tabs are this panel's header, so the strip matches the fixed height and border of
 *  the tab bar on its left (TabbedPanel) and of the review toolbar. */
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
            bottom border, the way the left pane's tabs underline does.
            The z-10 lifts the indicator above the active trigger, whose
            opaque rounded background (quill: trigger z-1, indicator z-0)
            otherwise covers the underline's top edge and leaves its ends
            poking out as rounded-looking nubs. The underscores are escaped
            because Tailwind turns bare underscores in arbitrary variants
            into spaces, so the unescaped form matches nothing. */}
        <TabsList
          variant="line"
          aria-label="Activity"
          className="h-[31px] gap-0.5 p-0 [&_.quill-tabs\_\_indicator]:z-10"
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

  // Not handleTabChange: a programmatic switch isn't a user tab change.
  useCommentFocusRequest(taskId, () => setTab("comments"));

  // A caller can open the panel pointed at a tab (the feed's comment chip
  // lands on Comments, its "+N files" rows on Artifacts). Applied once, then
  // consumed in the store — a local ref would reset when the panel remounts
  // (collapse/expand) and replay the stale request over the user's tab pick.
  const tabRequest = useThreadPanelStore(
    (state) => state.tabRequestByTask[taskId],
  );
  const consumeTabRequest = useThreadPanelStore(
    (state) => state.consumeTabRequest,
  );
  useEffect(() => {
    if (!tabRequest) return;
    setTab(tabRequest.tab);
    consumeTabRequest(taskId, tabRequest.nonce);
  }, [tabRequest, consumeTabRequest, taskId]);

  return (
    <div className="flex h-full min-w-0 flex-col bg-gray-1">
      <ActivityHeader
        tab={tab}
        onTabChange={handleTabChange}
        onOpenFull={onOpenFull}
        onToggleCollapsed={onToggleCollapsed}
        onClose={onClose}
      />

      {showTaskSummary && <TaskSummaryRow task={task} channelId={channelId} />}
      {/* Keyed by session: the body latches "the timeline has drawn" so it
          never blinks back to a loader, and the dock reuses one body across
          tasks, which would carry that latch onto a session still loading. */}
      <ActivityPanelBody
        key={taskId}
        task={task}
        tab={tab}
        canOpenInPlace={canOpenInPlace}
      />
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

  // Warmed from the id alone so it doesn't queue behind the task itself, which can take
  // seconds to arrive. Same query key as the panel's own hook, so this shares one fetch.
  useTaskThread(taskId, { enabled: !collapsed, markActivityRead: false });

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
