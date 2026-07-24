import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";
import { ThreadPanel } from "@posthog/ui/features/canvas/components/ThreadPanel";
import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { track } from "@posthog/ui/shell/analytics";
import { useState } from "react";

// The right-hand dock hosting a task's ThreadPanel: a thin rail when
// collapsed, a resizable sidebar otherwise. Shared by the channel feed and the
// task detail route; owns the panel-store size/collapse reads so parents don't
// re-render on every resize tick.
export function ThreadSidebar({
  taskId,
  channelId,
  task,
  onClose,
  onOpenFull,
  showTaskSummary,
}: {
  taskId: string;
  channelId: string;
  /** The thread's task when the caller already has it; fetched otherwise. */
  task?: Task;
  onClose?: () => void;
  onOpenFull?: () => void;
  showTaskSummary?: boolean;
}) {
  const collapsed = useThreadPanelStore((s) => s.collapsed);
  const width = useThreadPanelStore((s) => s.width);
  const setWidth = useThreadPanelStore((s) => s.setWidth);
  const setCollapsed = useThreadPanelStore((s) => s.setCollapsed);
  const [isResizing, setIsResizing] = useState(false);

  const toggleCollapsed = (next: boolean) => {
    setCollapsed(next);
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: next ? "collapse_thread" : "expand_thread",
      surface: "thread_panel",
      task_id: taskId,
    });
  };

  if (collapsed) {
    return (
      <ThreadPanel
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
      <ThreadPanel
        taskId={taskId}
        channelId={channelId}
        task={task}
        onClose={onClose}
        onToggleCollapsed={() => toggleCollapsed(true)}
        onOpenFull={onOpenFull}
        showTaskSummary={showTaskSummary}
      />
    </ResizableSidebar>
  );
}
