import type {
  GridDefinition,
  GridPlacement,
} from "@posthog/core/canvas/gridLayoutSchemas";

/** A single cell of the grid, by column and row. */
export interface GridCell {
  col: number;
  row: number;
}

export function sameCell(a: GridCell | null, b: GridCell | null): boolean {
  if (!a || !b) return a === b;
  return a.col === b.col && a.row === b.row;
}

export interface GridRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

// Server-enforced height cap for a single placement.
export const MAX_PLACEMENT_HEIGHT = 40;

export function rectsOverlap(a: GridRect, b: GridRect): boolean {
  return (
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
  );
}

export function collides(
  candidate: GridRect,
  placements: GridPlacement[],
  ignoreId?: string,
): boolean {
  return placements.some(
    (placement) =>
      placement.id !== ignoreId && rectsOverlap(candidate, placement),
  );
}

// Clamp a rect into the grid: sizes to at least 1x1 (and the height cap), then
// position so the rect stays inside the columns.
export function clampRect(rect: GridRect, columns: number): GridRect {
  const w = Math.min(Math.max(1, rect.w), columns);
  const h = Math.min(Math.max(1, rect.h), MAX_PLACEMENT_HEIGHT);
  const x = Math.min(Math.max(0, rect.x), columns - w);
  const y = Math.max(0, rect.y);
  return { x, y, w, h };
}

// The grid cell under a pointer position, given the surface's bounding rect.
export function cellFromPoint(
  pointerX: number,
  pointerY: number,
  surface: { left: number; top: number; width: number },
  grid: GridDefinition,
): GridCell {
  const cellWidth = (surface.width + grid.gap) / grid.columns;
  const col = Math.floor((pointerX - surface.left) / cellWidth);
  const row = Math.floor(
    (pointerY - surface.top) / (grid.rowHeight + grid.gap),
  );
  return {
    col: Math.min(Math.max(0, col), grid.columns - 1),
    row: Math.max(0, row),
  };
}

// The normalized rect spanned by two cells (a drag's anchor and current cell).
export function rectFromCells(anchor: GridCell, current: GridCell): GridRect {
  const x = Math.min(anchor.col, current.col);
  const y = Math.min(anchor.row, current.row);
  return {
    x,
    y,
    w: Math.abs(anchor.col - current.col) + 1,
    h: Math.abs(anchor.row - current.row) + 1,
  };
}

// Rows the grid surface must render: content, plus room to draw below it.
export function surfaceRows(placements: GridPlacement[], minimum = 8): number {
  const bottom = placements.reduce(
    (lowest, placement) => Math.max(lowest, placement.y + placement.h),
    0,
  );
  return Math.max(minimum, bottom + 4);
}
