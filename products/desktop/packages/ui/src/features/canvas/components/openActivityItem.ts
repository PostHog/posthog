import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { selectActivityItem } from "@posthog/ui/features/canvas/stores/activityDetailStore";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { useThreadPanelStore } from "@posthog/ui/features/canvas/stores/threadPanelStore";
import {
  canvasCommentFocusKey,
  useCommentNavigationStore,
} from "@posthog/ui/features/sessions/commentNavigationStore";
import {
  navigateToChannelDashboard,
  navigateToChannelTask,
  navigateToTaskDetail,
} from "@posthog/ui/router/navigationBridge";

/** Where a feed row goes on a surface that navigates. The rail's docked feed
 *  reads its row in place instead, so the row hands activation out. */
function focusActivityComment(item: TaskActivityItem, ownerKey: string): void {
  if (!item.commentId || !item.commentTarget) return;
  useCommentNavigationStore
    .getState()
    .requestCommentFocus(ownerKey, item.commentTarget, item.commentId);
}

export function openActivityItem(item: TaskActivityItem): void {
  const { channelId } = item;

  if (channelId && item.commentTarget?.scope === "canvas") {
    focusActivityComment(
      item,
      canvasCommentFocusKey(item.commentTarget.itemId),
    );
    useCanvasChatPanelStore.getState().openComments();
    navigateToChannelDashboard(channelId, item.commentTarget.itemId);
    return;
  }
  if (!item.taskId) return;
  focusActivityComment(item, item.taskId);
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

export function openActivityItemInRail(item: TaskActivityItem): void {
  if (!item.taskId) {
    openActivityItem(item);
    return;
  }
  focusActivityComment(item, item.taskId);
  selectActivityItem(item);
}
