export const REVIEW_FILE_CACHE_TIME_MS = 5 * 60_000;
export const REVIEW_PREFETCH_ROOT_MARGIN = "1500px 0px";
export const REVIEW_MAX_FILE_LINES = 5_000;
export const REVIEW_LIST_BUFFER_PX = 1_600;
export const REVIEW_LIST_ESTIMATED_ITEM_SIZE = 320;

/**
 * How wide the review has to be before it puts a file browser beside the diff.
 * Below this the browser would take the room the diff needs to stay readable,
 * which is the trade the toolbar's own file count already covers.
 */
export const REVIEW_FILE_BROWSER_MIN_WIDTH = 880;

export const DIFF_METRICS = {
  hunkLineCount: 50,
  lineHeight: 20,
  diffHeaderHeight: 31,
  hunkSeparatorHeight: 32,
  spacing: 8,
} as const;
