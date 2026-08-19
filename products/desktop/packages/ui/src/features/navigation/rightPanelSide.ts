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
  const { sideByKey, closedByDefault } = useRightPanelStore.getState();
  return resolveRightPanelSide({
    stored: sideByKey[taskId],
    closedByDefault,
    isReviewOpen: reviewMode !== "closed",
  });
}

/** What the keyboard does to the panel: open it, or put it away. */
export function toggleRightPanel(taskId: string): void {
  const open = currentRightPanelSide(taskId) != null;
  openRightPanelSide(open ? null : DEFAULT_RIGHT_PANEL_SIDE, taskId);
}

/**
 * How much of the content row's right edge the panel's switcher is sitting on.
 * Chrome that pins itself to that edge (the panel tree's tab strip and its
 * split and close controls) reads this and stops short, so the switcher can
 * float over the content pane without taking a column of its own or swallowing
 * the clicks meant for what is under it.
 */
export const CONTENT_CHROME_RIGHT_VAR = "--content-chrome-right";

/** Whether this session's panel is open, for chrome that has to make room. */
export function useRightPanelOpen(taskId: string | undefined): boolean {
  const stored = useRightPanelStore((s) =>
    taskId ? s.sideByKey[taskId] : undefined,
  );
  const closedByDefault = useRightPanelStore((s) => s.closedByDefault);
  const reviewMode = useReviewNavigationStore((s) =>
    taskId ? (s.reviewModes[taskId] ?? "closed") : "closed",
  );
  if (!taskId) return false;
  return (
    resolveRightPanelSide({
      stored,
      closedByDefault,
      isReviewOpen: reviewMode !== "closed",
    }) != null
  );
}
