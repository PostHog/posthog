const MARGIN = 96;
const MIN_WIDTH = 360;
const MIN_HEIGHT = 220;

export type ScreenshotArea = {
  x: number;
  y: number;
  width: number;
  height: number;
};

function span(
  start: number,
  end: number,
  minimum: number,
  limit: number,
): [number, number] {
  let from = start - MARGIN;
  let to = end + MARGIN;
  const missing = minimum - (to - from);
  if (missing > 0) {
    from -= missing / 2;
    to += missing / 2;
  }
  if (from < 0) {
    to -= from;
    from = 0;
  }
  if (to > limit) {
    from = Math.max(0, from - (to - limit));
    to = limit;
  }
  return [Math.round(from), Math.round(to)];
}

export type ScreenshotTarget = {
  top: number;
  left: number;
  right: number;
  bottom: number;
};

export function screenshotArea(
  element: ScreenshotTarget,
  viewport: { width: number; height: number },
): ScreenshotArea | null {
  if (viewport.width <= 0 || viewport.height <= 0) return null;
  const [left, right] = span(
    element.left,
    element.right,
    MIN_WIDTH,
    viewport.width,
  );
  const [top, bottom] = span(
    element.top,
    element.bottom,
    MIN_HEIGHT,
    viewport.height,
  );
  if (right - left <= 0 || bottom - top <= 0) return null;
  return { x: left, y: top, width: right - left, height: bottom - top };
}
