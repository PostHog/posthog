import { dedupeTaskIds } from "./selection";

/** How far the pointer travels before a press counts as a drag rather than a click. */
export const MARQUEE_THRESHOLD_PX = 4;

export interface MarqueeSpan {
  top: number;
  bottom: number;
}

export interface MarqueeRow {
  id: string;
  top: number;
  bottom: number;
}

export function hasDraggedFar(dx: number, dy: number): boolean {
  return (
    Math.abs(dx) >= MARQUEE_THRESHOLD_PX || Math.abs(dy) >= MARQUEE_THRESHOLD_PX
  );
}

/** The span between where the drag began and where it is now, either direction. */
export function marqueeSpan(originY: number, currentY: number): MarqueeSpan {
  return originY <= currentY
    ? { top: originY, bottom: currentY }
    : { top: currentY, bottom: originY };
}

/**
 * Rows the span touches. A session list is one column, so only the vertical
 * axis decides — dragging off to the side still selects what you dragged past.
 */
export function rowsInMarquee(
  span: MarqueeSpan,
  rows: readonly MarqueeRow[],
): string[] {
  return rows
    .filter((row) => row.bottom >= span.top && row.top <= span.bottom)
    .map((row) => row.id);
}

/**
 * A drag replaces the selection, as it does in a file manager. Holding the
 * modifier keeps what was selected when the drag began and adds to it.
 */
export function mergeMarqueeSelection(
  base: readonly string[],
  hit: readonly string[],
  additive: boolean,
): string[] {
  return additive ? dedupeTaskIds([...base, ...hit]) : [...hit];
}
