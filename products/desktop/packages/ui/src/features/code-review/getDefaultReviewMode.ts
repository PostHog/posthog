import type { ReviewMode } from "./reviewNavigationStore";

export const REVIEW_SPLIT_MIN_WINDOW_WIDTH = 1280;

export function getDefaultReviewMode(
  windowWidth = window.innerWidth,
): ReviewMode {
  return windowWidth >= REVIEW_SPLIT_MIN_WINDOW_WIDTH ? "split" : "expanded";
}
