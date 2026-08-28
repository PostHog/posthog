import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import { track } from "@posthog/ui/shell/analytics";

/**
 * Toggle the activity panel from the global shortcut. Reads the open thread
 * for the current channel directly from the stores (no hook), so it works
 * from anywhere in the channels layout, not just while a thread panel happens
 * to be mounted.
 */
export function toggleActivityPanel(): void {
  const { currentChannelId } = useCurrentChannelStore.getState();
  const openTaskId = currentChannelId
    ? useThreadPanelStore.getState().openByChannel[currentChannelId]
    : null;
  if (!openTaskId) return;

  const { collapsed, setCollapsed } = useThreadPanelStore.getState();
  setCollapsed(!collapsed);
  track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
    action_type: collapsed ? "expand_thread" : "collapse_thread",
    surface: "activity_panel",
    task_id: openTaskId,
  });
}
