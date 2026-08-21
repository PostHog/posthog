export const CHAT_CONTENT_MAX_WIDTH = 750;
/**
 * Horizontal room reserved on both sides of the thread's scroll content, and by the composer, so
 * the two columns narrow in step instead of one running wider than the other (and into the panel
 * edges). Wide enough to clear the minimap rail (44px from the right edge) while the pane can
 * afford it; once the gutter collapses toward the floor below, rows do pass under the rail.
 */
export const CHAT_CONTENT_GUTTER = 48;
/**
 * Floor the gutter collapses to once the pane is too narrow to hold the full one. Below this the
 * column would spend more of a cramped pane on empty margin than on the messages.
 */
export const CHAT_CONTENT_GUTTER_MIN = 24;
/**
 * `paddingInline` for anything that shares the chat column — thread rows, composer. Percentages
 * resolve against the pane, so the gutter tracks the pane's own width rather than the viewport's:
 * full while the pane can hold the column plus both gutters, sliding down to the floor as it
 * narrows.
 */
export const CHAT_CONTENT_PADDING_INLINE = `clamp(${CHAT_CONTENT_GUTTER_MIN}px, calc((100% - ${CHAT_CONTENT_MAX_WIDTH}px) / 2), ${CHAT_CONTENT_GUTTER}px)`;
/**
 * Narrowest the review-pane splitter may squeeze the chat pane to. Deliberately short of
 * CHAT_CONTENT_MAX_WIDTH + the gutters: the column shrinks gracefully below that, and holding the
 * full gutter here would cost the review pane room for no benefit.
 */
export const MIN_CHAT_WIDTH = CHAT_CONTENT_MAX_WIDTH + 16;
