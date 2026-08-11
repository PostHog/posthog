import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { ActivityPanel } from "@posthog/ui/features/canvas/components/ActivityPanel";
import { ThreadPanel } from "@posthog/ui/features/canvas/components/ThreadPanel";
import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { track } from "@posthog/ui/shell/analytics";
import { useState } from "react";

// The right-hand dock for a task's thread (collapsible, resizable). Flag on
// swaps the legacy ThreadPanel for the tabbed ActivityPanel.
export function ThreadSidebar({
  taskId,
  channelId,
  task,
  onClose,
  onOpenFull,
  showTaskSummary,
  canOpenInPlace,
}: {
  taskId: string;
  channelId: string;
  /** The thread's task when the caller already has it; fetched otherwise. */
  task?: Task;
  onClose?: () => void;
  onOpenFull?: () => void;
  showTaskSummary?: boolean;
  /** Set where the task's own view (transcript, review pane) is mounted beside
   *  this dock, so activity rows can drive it instead of going nowhere. */
  canOpenInPlace?: boolean;
}) {
  const collapsed = useThreadPanelStore((s) => s.collapsed);
  const width = useThreadPanelStore((s) => s.width);
  const setWidth = useThreadPanelStore((s) => s.setWidth);
  const setCollapsed = useThreadPanelStore((s) => s.setCollapsed);
  const [isResizing, setIsResizing] = useState(false);
  const channelsLayout = useChannelsLayout();
  const Panel = channelsLayout ? ActivityPanel : ThreadPanel;

  const toggleCollapsed = (next: boolean) => {
    setCollapsed(next);
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: next ? "collapse_thread" : "expand_thread",
      surface: channelsLayout ? "activity_panel" : "thread_panel",
      task_id: taskId,
    });
  };

  const panelProps = {
    taskId,
    channelId,
    task,
    onClose,
    onToggleCollapsed: () => toggleCollapsed(true),
    onOpenFull,
    showTaskSummary,
  };

  if (collapsed) {
    return (
      <Panel
        taskId={taskId}
        channelId={channelId}
        task={task}
        collapsed
        onToggleCollapsed={() => toggleCollapsed(false)}
      />
    );
  }

  return (
    <ResizableSidebar
      open
      width={width}
      setWidth={setWidth}
      isResizing={isResizing}
      setIsResizing={setIsResizing}
      side="right"
    >
      {channelsLayout ? (
        <ActivityPanel {...panelProps} canOpenInPlace={canOpenInPlace} />
      ) : (
        <ThreadPanel {...panelProps} />
      )}
    </ResizableSidebar>
  );
}
