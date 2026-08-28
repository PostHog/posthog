export type LayoutPreset =
  | "1x1"
  | "2x1"
  | "3x1"
  | "1x2"
  | "2x2"
  | "3x2"
  | "1x3"
  | "2x3"
  | "3x3";

export type ExpandDirection = "horizontal" | "vertical";

// Both axes cap at 3, so every preset is a cols/rows pair within that square.
const MAX_SPAN = 3;

export interface GridDimensions {
  cols: number;
  rows: number;
}

export const ZOOM_MIN = 0.5;
export const ZOOM_MAX = 1.5;
export const ZOOM_STEP = 0.1;

// Reserved cell value for the Brainrot video slot instead of a task. Real task
// ids are uuids, so this never collides with one.
export const BRAINROT_CELL = "__brainrot__";

export function isBrainrotCell(value: string | null): boolean {
  return value === BRAINROT_CELL;
}

// Reserved prefix for canvas cells. Canvas and task ids are UUIDs, so this
// cannot collide with either kind of real id.
export const CANVAS_CELL_PREFIX = "__canvas__:";

export function isCanvasCell(value: string | null): value is string {
  return value?.startsWith(CANVAS_CELL_PREFIX) ?? false;
}

export function makeCanvasCellValue(canvasId: string): string {
  return `${CANVAS_CELL_PREFIX}${canvasId}`;
}

export function getCanvasCellId(value: string | null): string | null {
  if (!isCanvasCell(value)) return null;
  return value.slice(CANVAS_CELL_PREFIX.length) || null;
}

// Reserved prefix for standalone terminal cells. Never collides with a task id
// (uuids) or with BRAINROT_CELL ("__brainrot__").
export const TERMINAL_CELL_PREFIX = "__terminal__:";

export function isTerminalCell(value: string | null): value is string {
  return value?.startsWith(TERMINAL_CELL_PREFIX) ?? false;
}

// terminalId is a base36 random string (no colon), so an optional cwd can be
// appended after a colon. cwd is URI-encoded, so it never contains a colon.
export function makeTerminalCellValue(
  terminalId: string,
  cwd?: string,
): string {
  const base = `${TERMINAL_CELL_PREFIX}${terminalId}`;
  return cwd ? `${base}:${encodeURIComponent(cwd)}` : base;
}

export function getTerminalCellId(value: string | null): string | null {
  if (!isTerminalCell(value)) return null;
  const rest = value.slice(TERMINAL_CELL_PREFIX.length);
  const colon = rest.indexOf(":");
  return colon === -1 ? rest : rest.slice(0, colon);
}

export function getTerminalCellCwd(value: string | null): string | null {
  if (!isTerminalCell(value)) return null;
  const rest = value.slice(TERMINAL_CELL_PREFIX.length);
  const colon = rest.indexOf(":");
  return colon === -1 ? null : decodeURIComponent(rest.slice(colon + 1));
}

/**
 * How many cells hold a task that still exists.
 *
 * Cells are persisted and only pruned when a task is archived — deleting one
 * leaves its id behind forever — so a count has to be taken against the live
 * task list rather than trusting the array's length. Excludes the brainrot and
 * terminal sentinels, which are ambient chrome rather than parked work.
 */
export function countActiveTaskCells(
  cells: readonly (string | null)[],
  liveTaskIds: ReadonlySet<string>,
): number {
  return cells.filter((cell) => cell != null && liveTaskIds.has(cell)).length;
}

export function getGridDimensions(preset: LayoutPreset): GridDimensions {
  const [cols, rows] = preset.split("x").map(Number);
  return { cols, rows };
}

export function getCellCount(preset: LayoutPreset): number {
  const { cols, rows } = getGridDimensions(preset);
  return cols * rows;
}

/** The preset one column wider or one row taller, or null at the 3x3 ceiling. */
export function getExpandedLayout(
  preset: LayoutPreset,
  direction: ExpandDirection,
): LayoutPreset | null {
  const { cols, rows } = getGridDimensions(preset);
  const grown =
    direction === "horizontal"
      ? { cols: cols + 1, rows }
      : { cols, rows: rows + 1 };
  if (grown.cols > MAX_SPAN || grown.rows > MAX_SPAN) return null;
  return `${grown.cols}x${grown.rows}` as LayoutPreset;
}

/**
 * The cell at `slot` of the column or row an expansion adds, in the expanded
 * layout's indices — the rightmost cell of row `slot`, or the bottom cell of
 * column `slot`. Picking an expand slot has to land in the space that just
 * opened, not in some empty tile elsewhere in the grid.
 */
export function getExpansionCellIndex(
  expanded: LayoutPreset,
  direction: ExpandDirection,
  slot: number,
): number {
  const { cols, rows } = getGridDimensions(expanded);
  return direction === "horizontal"
    ? slot * cols + (cols - 1)
    : (rows - 1) * cols + slot;
}

/**
 * The tightest layout that holds `count` tiles, kept as square as the presets
 * allow and never taller than it is wide: 3 tiles fit 2x2 rather than 3x1, and
 * 5 fit 3x2. Above 9 it saturates at the largest grid.
 */
export function getOptimalLayout(count: number): LayoutPreset {
  const cols = Math.min(MAX_SPAN, Math.max(1, Math.ceil(Math.sqrt(count))));
  const rows = Math.min(MAX_SPAN, Math.max(1, Math.ceil(count / cols)));
  return `${cols}x${rows}` as LayoutPreset;
}

/**
 * Fewest tiles wins, then the squarer shape, then the wider one — matching
 * `getOptimalLayout`, which is never taller than it is wide.
 */
function isBetterFit(a: GridDimensions, b: GridDimensions): boolean {
  const [areaA, areaB] = [a.cols * a.rows, b.cols * b.rows];
  if (areaA !== areaB) return areaA < areaB;
  const [skewA, skewB] = [Math.abs(a.cols - a.rows), Math.abs(b.cols - b.rows)];
  if (skewA !== skewB) return skewA < skewB;
  return a.cols > b.cols;
}

/**
 * The smallest layout holding `needed` tiles without shrinking either axis of
 * `current`. Unlike `getOptimalLayout`, which picks the tightest shape for a
 * count in isolation, this only ever grows: dropping from 1x3 to 3x2 would fit
 * more tiles overall but `reflowCells` would discard whatever sat in row 3.
 */
export function getLayoutToFit(
  current: LayoutPreset,
  needed: number,
): LayoutPreset {
  const from = getGridDimensions(current);
  if (needed <= from.cols * from.rows) return current;

  let best: GridDimensions | null = null;
  for (let cols = from.cols; cols <= MAX_SPAN; cols++) {
    for (let rows = from.rows; rows <= MAX_SPAN; rows++) {
      if (cols * rows < needed) continue;
      if (!best || isBetterFit({ cols, rows }, best)) best = { cols, rows };
    }
  }
  // Nothing within the 3x3 ceiling fits, so grow as far as the ceiling allows.
  const { cols, rows } = best ?? { cols: MAX_SPAN, rows: MAX_SPAN };
  return `${cols}x${rows}` as LayoutPreset;
}

export function resizeCells(
  current: (string | null)[],
  newCount: number,
): (string | null)[] {
  if (current.length === newCount) return current;
  if (current.length > newCount) return current.slice(0, newCount);
  return [...current, ...Array(newCount - current.length).fill(null)];
}

/**
 * Cells for a new grid shape, keeping each one in the same row and column.
 * Cells are stored row-major, so a column change moves every row's start —
 * padding the tail instead would shuffle tiles between rows. Cells outside the
 * new shape are dropped.
 */
export function reflowCells(
  cells: readonly (string | null)[],
  from: LayoutPreset,
  to: LayoutPreset,
): (string | null)[] {
  const source = getGridDimensions(from);
  const target = getGridDimensions(to);
  if (source.cols === target.cols)
    return resizeCells([...cells], getCellCount(to));

  const next: (string | null)[] = Array(getCellCount(to)).fill(null);
  const rows = Math.min(source.rows, target.rows);
  const cols = Math.min(source.cols, target.cols);
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      next[row * target.cols + col] = cells[row * source.cols + col] ?? null;
    }
  }
  return next;
}

export function clampZoom(value: number): number {
  return Math.round(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value)) * 10) / 10;
}
