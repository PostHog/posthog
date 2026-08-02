export const CHAT_CONTENT_MAX_WIDTH = 750;
/**
 * Horizontal room reserved on both sides of the thread's scroll content, and by the composer, so
 * the two columns narrow in step instead of one running wider than the other (and into the panel
 * edges) once the panel is too narrow for the full column. Wide enough to clear the minimap rail
 * (44px from the right edge), so rows never pass underneath it.
 */
export const CHAT_CONTENT_GUTTER = 48;
/**
 * Narrowest the review-pane splitter may squeeze the chat pane to. Deliberately short of
 * CHAT_CONTENT_MAX_WIDTH + the gutters: the column shrinks gracefully below that, and holding the
 * full gutter here would cost the review pane room for no benefit.
 */
export const MIN_CHAT_WIDTH = CHAT_CONTENT_MAX_WIDTH + 16;
