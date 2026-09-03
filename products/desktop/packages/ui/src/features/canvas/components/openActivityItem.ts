import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import {
  navigateToChannelDashboard,
  navigateToChannelTask,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";

/** Where a feed row goes on a surface that navigates. The rail's docked feed
 *  reads its row in place instead, so the row hands activation out. */
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
