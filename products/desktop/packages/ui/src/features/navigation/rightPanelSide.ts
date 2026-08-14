import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import {
  DEFAULT_RIGHT_PANEL_SIDE,
  type RightPanelSide,
  resolveRightPanelSide,
  useRightPanelStore,
} from "@posthog/ui/features/navigation/rightPanelStore";

/**
 * Put a session's right panel on a side, or close it with `null`. Changes rides
 * the review store so the command menu, PR links, and diff toggles that already
 * open review all land on the same panel, and so that picking another panel
 * closes what they opened.
 */
export function openRightPanelSide(
  side: RightPanelSide | null,
  taskId: string,
): void {
  useRightPanelStore.getState().setSideForKey(taskId, side);
  useReviewNavigationStore
    .getState()
    .setReviewMode(taskId, side === "changes" ? "split" : "closed");
}

/** The side a session's panel is showing, outside a React render. */
export function currentRightPanelSide(taskId: string): RightPanelSide | null {
  const reviewMode =
    useReviewNavigationStore.getState().reviewModes[taskId] ?? "closed";
  return resolveRightPanelSide({
    stored: useRightPanelStore.getState().sideByKey[taskId],
    isReviewOpen: reviewMode !== "closed",
  });
}

/** What the keyboard does to the panel: open it, or put it away. */
export function toggleRightPanel(taskId: string): void {
  const open = currentRightPanelSide(taskId) != null;
  openRightPanelSide(open ? null : DEFAULT_RIGHT_PANEL_SIDE, taskId);
}
