/**
 * Placement math for the quick-ask panel, kept free of electron imports so
 * the decisions are unit-testable.
 *
 * Everything about the panel's placement derives from one fact — where the
 * pill row's top-left corner sits on screen — plus the content size and the
 * display's work area. `computeGeometry` is that pure function, re-evaluated
 * on every content change, so the grow direction is a living decision: a
 * panel summoned low on the screen starts growing upward the moment the
 * answer needs the room, instead of being stuck with whatever direction
 * made sense when it was an empty pill.
 */

// Layout constants matching quick-ask.css: root padding top/bottom 10/14,
// pill row 46px, card gap 10px.
export const ROOT_PAD_TOP = 10;
export const ROOT_PAD_BOTTOM = 14;
export const PILL_ROW_HEIGHT = 46;
export const PILL_HEIGHT = ROOT_PAD_TOP + PILL_ROW_HEIGHT + ROOT_PAD_BOTTOM;
// Keep the panel clear of the menu bar and screen edges.
export const SCREEN_MARGIN = 16;
export const MENU_BAR_CLEARANCE = 40;
// Distance between the pill row's top edge and the window edge in each
// grow direction (root padding; plus the pill row itself when flipped).
export const PILL_TOP_TO_WINDOW_TOP = ROOT_PAD_TOP;
export const PILL_TOP_TO_WINDOW_BOTTOM = PILL_ROW_HEIGHT + ROOT_PAD_BOTTOM;

export interface Point {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

export interface Rect extends Point, Size {}

export interface QuickAskGeometry extends Rect {
  /** Card renders above the pill. */
  flip: boolean;
  /** Room between the pill's anchor and the screen edge, in CSS pixels. */
  maxHeight: number;
}

export function computeGeometry(
  anchor: Point,
  content: Size,
  workArea: Rect,
  prevFlip: boolean,
): QuickAskGeometry {
  const roomBelow =
    workArea.y +
    workArea.height -
    SCREEN_MARGIN -
    (anchor.y - PILL_TOP_TO_WINDOW_TOP);
  const roomAbove =
    anchor.y + PILL_TOP_TO_WINDOW_BOTTOM - (workArea.y + MENU_BAR_CLEARANCE);
  // Keep the current direction while the content fits there (no side
  // jumping mid-answer); otherwise grow toward the roomier side.
  let flip = prevFlip;
  if (content.height > (flip ? roomAbove : roomBelow)) {
    flip = roomAbove > roomBelow;
  }
  const maxHeight = Math.max(PILL_HEIGHT, flip ? roomAbove : roomBelow);
  const height = Math.max(PILL_HEIGHT, Math.min(content.height, maxHeight));
  const y = flip
    ? anchor.y + PILL_TOP_TO_WINDOW_BOTTOM - height
    : anchor.y - PILL_TOP_TO_WINDOW_TOP;
  return {
    x: anchor.x,
    y: Math.round(y),
    width: content.width,
    height,
    flip,
    maxHeight,
  };
}
