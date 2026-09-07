import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";

/**
 * Reports a filing from a task's own context menu. Shared, because reporting
 * from one of the two such menus reads as if the other is unused.
 */
export function trackFileTask(
  channelId: string,
  taskId: string,
  success: boolean,
): void {
  track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
    action_type: "file_task",
    surface: "task_context_menu",
    channel_id: channelId,
    task_id: taskId,
    success,
  });
}
