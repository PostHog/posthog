export const CHAT_CONTENT_MAX_WIDTH = 750;
/**
 * Horizontal room reserved on both sides of the thread's scroll content. The minimap rail hugs the
 * scroll container rather than the column, so this keeps rows off it once the panel is too narrow
 * for the column's own slack; the left side mirrors it to keep the column centred.
 */
export const CHAT_CONTENT_GUTTER = 32;
export const CHAT_CONTENT_PADDING = 8;
export const MIN_CHAT_WIDTH = CHAT_CONTENT_MAX_WIDTH + CHAT_CONTENT_PADDING * 2;
