export const RIGHT_PANEL_MIN_WIDTH = 280;
export const RIGHT_PANEL_DEFAULT_WIDTH = 340;

/**
 * The most of its row the panel pushes the pane out of before it covers it
 * instead. Past this the pane no longer reflows, which is what makes widening
 * the panel cheap.
 */
const PUSH_MAX_SHARE = 0.5;

/** What the panel always leaves of the row, so there is pane left to click. */
const ROW_INSET_PX = 50;

/** Drag past half the floor to close; back out past this to reopen. The gap stops jitter. */
const DRAG_CLOSE_AT = RIGHT_PANEL_MIN_WIDTH * 0.5;
const DRAG_REOPEN_AT = DRAG_CLOSE_AT + 16;

/** The spacer's CSS width, as a share of the row it sits in. */
export const PUSH_MAX_CSS = `${PUSH_MAX_SHARE * 100}%`;

/** The panel's CSS ceiling, as an inset off the row's far edge. */
export const ROW_CEILING_CSS = `calc(100% - ${ROW_INSET_PX}px)`;

/** Widest the panel may be drawn in a row this wide. */
export function panelCeiling(rowWidth: number): number {
  return Math.max(0, rowWidth - ROW_INSET_PX);
}

/** A dragged width held to the panel's floor and the row's ceiling. */
export function resolvePanelWidth(stored: number, rowWidth: number): number {
  const ceiling = panelCeiling(rowWidth);
  return Math.max(
    Math.min(RIGHT_PANEL_MIN_WIDTH, ceiling),
    Math.min(stored, ceiling),
  );
}

export interface PanelGeometry {
  /** Over the pane rather than beside it. */
  covering: boolean;
  /** As wide as the row allows, however it got there. */
  atFullWidth: boolean;
  /** Widest the panel gets while still pushing rather than covering. */
  uncoveredWidth: number;
}

/** Where the panel sits in its row. An unmeasured row can't say, so it says nothing. */
export function resolvePanelGeometry({
  storedWidth,
  rowWidth,
  open,
  expanded,
}: {
  storedWidth: number;
  rowWidth: number;
  open: boolean;
  expanded: boolean;
}): PanelGeometry {
  if (!open || rowWidth <= 0) {
    return { covering: false, atFullWidth: false, uncoveredWidth: 0 };
  }
  const uncoveredWidth = rowWidth * PUSH_MAX_SHARE;
  return {
    uncoveredWidth,
    covering: expanded || storedWidth > uncoveredWidth,
    atFullWidth: expanded || storedWidth >= panelCeiling(rowWidth),
  };
}

/** What a drag is asking of the panel. */
export type PanelDrag =
  | { action: "resize"; width: number }
  /** Out of the full row and back to a width of its own, mid-drag. */
  | { action: "collapse"; width: number }
  | { action: "close" }
  | { action: "reopen"; width: number }
  /** Nowhere the panel has an answer for. */
  | { action: "hold" };

/**
 * What the pointer's distance from the row's right edge means. At full width
 * there is nothing wider to ask for, so dragging out holds and dragging in is
 * how expanding comes undone.
 */
export function resolvePanelDrag({
  pointer,
  rowWidth,
  open,
  expanded,
}: {
  /** The pointer's distance from the row's right edge. */
  pointer: number;
  rowWidth: number;
  open: boolean;
  expanded: boolean;
}): PanelDrag {
  const width = resolvePanelWidth(pointer, rowWidth);

  if (expanded) {
    return width >= panelCeiling(rowWidth)
      ? { action: "hold" }
      : { action: "collapse", width };
  }
  if (open) {
    return pointer < DRAG_CLOSE_AT
      ? { action: "close" }
      : { action: "resize", width };
  }
  return pointer >= DRAG_REOPEN_AT
    ? { action: "reopen", width }
    : { action: "hold" };
}
