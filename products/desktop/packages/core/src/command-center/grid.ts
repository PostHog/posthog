export type LayoutPreset = "1x1" | "2x1" | "1x2" | "2x2" | "3x2" | "3x3";

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

export function getGridDimensions(preset: LayoutPreset): GridDimensions {
  const [cols, rows] = preset.split("x").map(Number);
  return { cols, rows };
}

export function getCellCount(preset: LayoutPreset): number {
  const { cols, rows } = getGridDimensions(preset);
  return cols * rows;
}

export function resizeCells(
  current: (string | null)[],
  newCount: number,
): (string | null)[] {
  if (current.length === newCount) return current;
  if (current.length > newCount) return current.slice(0, newCount);
  return [...current, ...Array(newCount - current.length).fill(null)];
}

export function clampZoom(value: number): number {
  return Math.round(Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value)) * 10) / 10;
}

export function getCellSessionId(cellIndex: number): string {
  return `cc-cell-${cellIndex}`;
}
