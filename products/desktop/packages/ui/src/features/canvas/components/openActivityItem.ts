import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import {
  navigateToChannelDashboard,
  navigateToChannelTask,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";

/**
 * Where a feed row goes when it is opened on a surface that navigates.
 *
 * Every activity surface except the rail's docked feed ends up here — the feed
 * reads its row in the pane beside it instead, which is why the row itself
 * hands activation out rather than deciding.
 */
export function openActivityItem(item: TaskActivityItem): void {
  const { channelId } = item;

  if (channelId && item.commentTarget?.scope === "desktop_canvas") {
    useCanvasChatPanelStore.getState().openComments();
    navigateToChannelDashboard(channelId, item.commentTarget.itemId);
    return;
  }
  // The channel thread route is the deep-link target; unfiled tasks fall back
  // to the plain task view.
  if (channelId) {
    if (item.commentId) {
      useThreadPanelStore.getState().setCollapsed(false);
    }
    navigateToChannelTask(channelId, item.taskId);
    return;
  }
  navigateToTaskDetail(item.taskId);
}
