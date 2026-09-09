import type { SketchpadFragment, SketchpadViewport } from "@posthog/shared";

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

export interface SketchpadPoint {
  x: number;
  y: number;
}

export interface SketchpadRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SketchpadScreenRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface SketchpadPaneRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface SketchpadSize {
  w: number;
  h: number;
}

export type SketchpadBox = Pick<SketchpadFragment, "x" | "y" | "w" | "h">;

export const SKETCHPAD_MIN_ZOOM = 0.1;
export const SKETCHPAD_MAX_ZOOM = 4;
export const SKETCHPAD_FIT_MAX_ZOOM = 1;
export const SKETCHPAD_FIT_PADDING = 64;
export const SKETCHPAD_GRID = 8;
export const SKETCHPAD_MIN_FRAGMENT_SIZE: SketchpadSize = { w: 120, h: 80 };

export function clampZoom(zoom: number): number {
  if (!Number.isFinite(zoom)) return 1;
  return Math.min(SKETCHPAD_MAX_ZOOM, Math.max(SKETCHPAD_MIN_ZOOM, zoom));
}

export function screenToWorld(
  point: SketchpadPoint,
  viewport: SketchpadViewport,
  paneRect: SketchpadPaneRect,
): SketchpadPoint {
  return {
    x: (point.x - paneRect.left - viewport.x) / viewport.zoom,
    y: (point.y - paneRect.top - viewport.y) / viewport.zoom,
  };
}

export function worldToScreen(
  point: SketchpadPoint,
  viewport: SketchpadViewport,
  paneRect: SketchpadPaneRect,
): SketchpadPoint {
  return {
    x: point.x * viewport.zoom + viewport.x + paneRect.left,
    y: point.y * viewport.zoom + viewport.y + paneRect.top,
  };
}

export function fragmentScreenRect(
  fragment: SketchpadBox,
  viewport: SketchpadViewport,
  paneRect: SketchpadPaneRect,
): SketchpadScreenRect {
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

export function zoomAround(
  viewport: SketchpadViewport,
  screenPoint: SketchpadPoint,
  factor: number,
  paneRect: SketchpadPaneRect,
): SketchpadViewport {
  const zoom = clampZoom(viewport.zoom * factor);
  const world = screenToWorld(screenPoint, viewport, paneRect);
  return {
    x: screenPoint.x - paneRect.left - world.x * zoom,
    y: screenPoint.y - paneRect.top - world.y * zoom,
    zoom,
  };
}

export function zoomAroundCenter(
  viewport: SketchpadViewport,
  factor: number,
  paneRect: SketchpadPaneRect,
): SketchpadViewport {
  return zoomAround(viewport, paneCenter(paneRect), factor, paneRect);
}

export function zoomTo(
  viewport: SketchpadViewport,
  zoom: number,
  paneRect: SketchpadPaneRect,
): SketchpadViewport {
  return zoomAroundCenter(viewport, clampZoom(zoom) / viewport.zoom, paneRect);
}

export function panBy(
  viewport: SketchpadViewport,
  dx: number,
  dy: number,
): SketchpadViewport {
  return { x: viewport.x + dx, y: viewport.y + dy, zoom: viewport.zoom };
}

export function fitToContent(
  fragments: readonly SketchpadBox[],
  paneRect: SketchpadPaneRect,
): SketchpadViewport {
  const bounds = contentBounds(fragments);
  if (!bounds) return { x: 0, y: 0, zoom: 1 };

  const paneWidth = Math.max(1, paneRect.width - SKETCHPAD_FIT_PADDING * 2);
  const paneHeight = Math.max(1, paneRect.height - SKETCHPAD_FIT_PADDING * 2);
  const zoom = clampZoom(
    Math.min(
      SKETCHPAD_FIT_MAX_ZOOM,
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
  fragments: readonly SketchpadBox[],
): SketchpadRect | null {
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

export const SKETCHPAD_MARGIN = 800;
export const SKETCHPAD_MIN_EXTENT = 2400;

export function sketchpadBounds(
  fragments: readonly SketchpadBox[],
): SketchpadRect {
  const content = contentBounds(fragments);
  if (!content) {
    const half = SKETCHPAD_MIN_EXTENT / 2;
    return {
      x: -half,
      y: -half,
      w: SKETCHPAD_MIN_EXTENT,
      h: SKETCHPAD_MIN_EXTENT,
    };
  }
  const w = Math.max(content.w + SKETCHPAD_MARGIN * 2, SKETCHPAD_MIN_EXTENT);
  const h = Math.max(content.h + SKETCHPAD_MARGIN * 2, SKETCHPAD_MIN_EXTENT);
  return {
    x: content.x + content.w / 2 - w / 2,
    y: content.y + content.h / 2 - h / 2,
    w,
    h,
  };
}

export function clampViewport(
  viewport: SketchpadViewport,
  pane: SketchpadSize,
  bounds: SketchpadRect,
): SketchpadViewport {
  const zoom = clampZoom(viewport.zoom);
  return {
    zoom,
    x: clampAxis(viewport.x, pane.w, bounds.x, bounds.w, zoom),
    y: clampAxis(viewport.y, pane.h, bounds.y, bounds.h, zoom),
  };
}

function clampAxis(
  offset: number,
  paneExtent: number,
  boundsStart: number,
  boundsExtent: number,
  zoom: number,
): number {
  const drawn = boundsExtent * zoom;
  const start = -boundsStart * zoom;
  if (drawn <= paneExtent) return start - (drawn - paneExtent) / 2;
  return Math.min(start, Math.max(start - (drawn - paneExtent), offset));
}

export function resizeRect(
  rect: SketchpadRect,
  handle: ResizeHandle,
  dx: number,
  dy: number,
  min: SketchpadSize = SKETCHPAD_MIN_FRAGMENT_SIZE,
): SketchpadRect {
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

export function rectFromPoints(
  a: SketchpadPoint,
  b: SketchpadPoint,
): SketchpadRect {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    w: Math.abs(a.x - b.x),
    h: Math.abs(a.y - b.y),
  };
}

export function rectsTouch(rect: SketchpadRect, box: SketchpadBox): boolean {
  return (
    rect.x <= box.x + box.w &&
    rect.x + rect.w >= box.x &&
    rect.y <= box.y + box.h &&
    rect.y + rect.h >= box.y
  );
}

export function snapToGrid(
  value: number,
  grid: number = SKETCHPAD_GRID,
): number {
  if (grid <= 0) return value;
  return Math.round(value / grid) * grid;
}

export function isOffPane(
  rect: SketchpadScreenRect,
  paneRect: SketchpadPaneRect,
): boolean {
  return (
    rect.left + rect.width < paneRect.left ||
    rect.top + rect.height < paneRect.top ||
    rect.left > paneRect.left + paneRect.width ||
    rect.top > paneRect.top + paneRect.height
  );
}

function paneCenter(paneRect: SketchpadPaneRect): SketchpadPoint {
  return {
    x: paneRect.left + paneRect.width / 2,
    y: paneRect.top + paneRect.height / 2,
  };
}
