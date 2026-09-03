import type { CanvasV2Fragment, CanvasV2Viewport } from "@posthog/shared";

/**
 * Board math. World units are CSS px at zoom 1, origin top left. Screen points
 * are client coordinates, the space pointer events report in, so the pane rect
 * from `getBoundingClientRect()` converts between the two.
 */

export type ResizeHandle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";

export const RESIZE_HANDLES: readonly ResizeHandle[] = [
  "nw",
  "n",
  "ne",
  "e",
  "se",
  "s",
  "sw",
  "w",
];

export interface BoardPoint {
  x: number;
  y: number;
}

export interface BoardRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface BoardScreenRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** The board pane in client coordinates, as `getBoundingClientRect()` gives it. */
export interface BoardPaneRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface BoardSize {
  w: number;
  h: number;
}

export type BoardBox = Pick<CanvasV2Fragment, "x" | "y" | "w" | "h">;

export const BOARD_MIN_ZOOM = 0.1;
export const BOARD_MAX_ZOOM = 4;
/** Fit never magnifies: a board with one small fragment stays readable. */
export const BOARD_FIT_MAX_ZOOM = 1;
export const BOARD_FIT_PADDING = 64;
export const BOARD_GRID = 8;
export const BOARD_MIN_FRAGMENT_SIZE: BoardSize = { w: 120, h: 80 };

export function clampZoom(zoom: number): number {
  if (!Number.isFinite(zoom)) return 1;
  return Math.min(BOARD_MAX_ZOOM, Math.max(BOARD_MIN_ZOOM, zoom));
}

export function screenToWorld(
  point: BoardPoint,
  viewport: CanvasV2Viewport,
  paneRect: BoardPaneRect,
): BoardPoint {
  return {
    x: (point.x - paneRect.left - viewport.x) / viewport.zoom,
    y: (point.y - paneRect.top - viewport.y) / viewport.zoom,
  };
}

export function worldToScreen(
  point: BoardPoint,
  viewport: CanvasV2Viewport,
  paneRect: BoardPaneRect,
): BoardPoint {
  return {
    x: point.x * viewport.zoom + viewport.x + paneRect.left,
    y: point.y * viewport.zoom + viewport.y + paneRect.top,
  };
}

export function fragmentScreenRect(
  fragment: BoardBox,
  viewport: CanvasV2Viewport,
  paneRect: BoardPaneRect,
): BoardScreenRect {
  const origin = worldToScreen(
    { x: fragment.x, y: fragment.y },
    viewport,
    paneRect,
  );
  return {
    left: origin.x,
    top: origin.y,
    width: fragment.w * viewport.zoom,
    height: fragment.h * viewport.zoom,
  };
}

/** Zooms by `factor` and keeps the world point under `screenPoint` in place. */
export function zoomAround(
  viewport: CanvasV2Viewport,
  screenPoint: BoardPoint,
  factor: number,
  paneRect: BoardPaneRect,
): CanvasV2Viewport {
  const zoom = clampZoom(viewport.zoom * factor);
  const world = screenToWorld(screenPoint, viewport, paneRect);
  return {
    x: screenPoint.x - paneRect.left - world.x * zoom,
    y: screenPoint.y - paneRect.top - world.y * zoom,
    zoom,
  };
}

export function zoomAroundCenter(
  viewport: CanvasV2Viewport,
  factor: number,
  paneRect: BoardPaneRect,
): CanvasV2Viewport {
  return zoomAround(viewport, paneCenter(paneRect), factor, paneRect);
}

/** Sets an absolute zoom and keeps the pane center in place. */
export function zoomTo(
  viewport: CanvasV2Viewport,
  zoom: number,
  paneRect: BoardPaneRect,
): CanvasV2Viewport {
  return zoomAroundCenter(viewport, clampZoom(zoom) / viewport.zoom, paneRect);
}

export function panBy(
  viewport: CanvasV2Viewport,
  dx: number,
  dy: number,
): CanvasV2Viewport {
  return { x: viewport.x + dx, y: viewport.y + dy, zoom: viewport.zoom };
}

/** A viewport that shows every fragment, with padding and no magnification. */
export function fitToContent(
  fragments: readonly BoardBox[],
  paneRect: BoardPaneRect,
): CanvasV2Viewport {
  const bounds = contentBounds(fragments);
  if (!bounds) return { x: 0, y: 0, zoom: 1 };

  const paneWidth = Math.max(1, paneRect.width - BOARD_FIT_PADDING * 2);
  const paneHeight = Math.max(1, paneRect.height - BOARD_FIT_PADDING * 2);
  const zoom = clampZoom(
    Math.min(
      BOARD_FIT_MAX_ZOOM,
      paneWidth / Math.max(1, bounds.w),
      paneHeight / Math.max(1, bounds.h),
    ),
  );
  return {
    x: (paneRect.width - bounds.w * zoom) / 2 - bounds.x * zoom,
    y: (paneRect.height - bounds.h * zoom) / 2 - bounds.y * zoom,
    zoom,
  };
}

export function contentBounds(
  fragments: readonly BoardBox[],
): BoardRect | null {
  if (fragments.length === 0) return null;
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const fragment of fragments) {
    minX = Math.min(minX, fragment.x);
    minY = Math.min(minY, fragment.y);
    maxX = Math.max(maxX, fragment.x + fragment.w);
    maxY = Math.max(maxY, fragment.y + fragment.h);
  }
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
}

/** Moves the edges the handle owns and keeps the opposite edges fixed. */
export function resizeRect(
  rect: BoardRect,
  handle: ResizeHandle,
  dx: number,
  dy: number,
  min: BoardSize = BOARD_MIN_FRAGMENT_SIZE,
): BoardRect {
  const next = { ...rect };
  if (handle.includes("e")) {
    next.w = Math.max(min.w, rect.w + dx);
  }
  if (handle.includes("s")) {
    next.h = Math.max(min.h, rect.h + dy);
  }
  if (handle.includes("w")) {
    next.w = Math.max(min.w, rect.w - dx);
    next.x = rect.x + rect.w - next.w;
  }
  if (handle.includes("n")) {
    next.h = Math.max(min.h, rect.h - dy);
    next.y = rect.y + rect.h - next.h;
  }
  return next;
}

/** The box two opposite corners span, whatever order the corners come in. */
export function rectFromPoints(a: BoardPoint, b: BoardPoint): BoardRect {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    w: Math.abs(a.x - b.x),
    h: Math.abs(a.y - b.y),
  };
}

/** True when the two boxes touch or overlap. Edge contact counts. */
export function rectsTouch(rect: BoardRect, box: BoardBox): boolean {
  return (
    rect.x <= box.x + box.w &&
    rect.x + rect.w >= box.x &&
    rect.y <= box.y + box.h &&
    rect.y + rect.h >= box.y
  );
}

export function snapToGrid(value: number, grid: number = BOARD_GRID): number {
  if (grid <= 0) return value;
  return Math.round(value / grid) * grid;
}

/** True when no part of the rect is inside the pane. */
export function isOffPane(
  rect: BoardScreenRect,
  paneRect: BoardPaneRect,
): boolean {
  return (
    rect.left + rect.width < paneRect.left ||
    rect.top + rect.height < paneRect.top ||
    rect.left > paneRect.left + paneRect.width ||
    rect.top > paneRect.top + paneRect.height
  );
}

function paneCenter(paneRect: BoardPaneRect): BoardPoint {
  return {
    x: paneRect.left + paneRect.width / 2,
    y: paneRect.top + paneRect.height / 2,
  };
}
