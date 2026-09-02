import {
  ChatCircleIcon,
  GitDiffIcon,
  type Icon,
  PackageIcon,
  PulseIcon,
} from "@phosphor-icons/react";
import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";
import {
  DEFAULT_RIGHT_PANEL_SIDE,
  type RightPanelSide,
  resolveRightPanelSide,
  useRightPanelStore,
} from "@posthog/ui/features/navigation/rightPanelStore";

/**
 * Changes rides the review store, so every entry point into a review lands on
 * the same panel and picking another panel closes what they opened.
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
 * How much of the row's right edge the switcher sits on. Chrome pinned to that
 * edge reads this and stops short, so the switcher can float over the pane.
 */
export const CONTENT_CHROME_RIGHT_VAR = "--content-chrome-right";

/** Room for one button per side at icon-sm, kept clear by pane and header alike. */
export const SWITCHER_WIDTH_PX = 112;

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

/** The panels the right column can show, in the order the switcher lists them. */
export const SIDES: Record<RightPanelSide, { label: string; Icon: Icon }> = {
  timeline: { label: "Timeline", Icon: PulseIcon },
  artifacts: { label: "Artifacts", Icon: PackageIcon },
  comments: { label: "Comments", Icon: ChatCircleIcon },
  changes: { label: "Changes", Icon: GitDiffIcon },
};

export const SIDE_ORDER: readonly RightPanelSide[] = [
  "timeline",
  "artifacts",
  "comments",
  "changes",
];
