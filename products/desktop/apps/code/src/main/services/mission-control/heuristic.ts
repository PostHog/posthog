import type { CgWindow, Rect } from "./window-list";

const DOCK = "Dock";

/**
 * The Dock's own window level, historically `NSDockWindowLevel`. Its window
 * spans the entire display — a long-standing CoreGraphics quirk — so this level
 * is what has to be excluded rather than matched.
 */
const DOCK_WINDOW_LEVEL = 20;

/**
 * A window can sit a pixel outside the display it covers, so compare with slack
 * rather than for equality.
 */
const COVERAGE_SLACK_PX = 2;

/** Whether `bounds` spans the whole of `display`. */
function coversDisplay(bounds: Rect, display: Rect): boolean {
  return (
    bounds.x <= display.x + COVERAGE_SLACK_PX &&
    bounds.y <= display.y + COVERAGE_SLACK_PX &&
    bounds.x + bounds.width >= display.x + display.width - COVERAGE_SLACK_PX &&
    bounds.y + bounds.height >= display.y + display.height - COVERAGE_SLACK_PX
  );
}

/**
 * macOS exposes no API, public or private, for "is Mission Control on screen".
 * The signal is that opening it makes the Dock put up a full-display window
 * between the normal window level and the Dock's own — layer 18 on macOS 26.
 *
 * Each clause earns its place, and the loose versions had visible symptoms:
 *
 *   - Below the Dock's level, because the Dock's own window is full-display too.
 *     Without this, hovering the Dock and Cmd-Tab both showed the overlay.
 *   - Above the normal level, which excludes the desktop wallpaper and a
 *     full-display Dock-owned window that also sits at layer 0.
 *   - Full-display, which excludes the Dock strip and the per-window badges
 *     Mission Control draws at layer 17.
 *
 * Undocumented and version-specific: an earlier revision keyed off a y origin of
 * -1, true on OS X 10.10 and false now. Re-derive it from a
 * `dev.probeMissionControl` recording rather than reasoning about it.
 *
 * App Exposé, Launchpad and Show Desktop are untested and may match. Harmless:
 * each either hides our window or slides it off screen.
 */
export function detectMissionControl(
  windows: CgWindow[],
  displays: Rect[],
): boolean {
  return windows.some(
    (window) =>
      window.ownerName === DOCK &&
      window.layer > 0 &&
      window.layer < DOCK_WINDOW_LEVEL &&
      displays.some((display) => coversDisplay(window.bounds, display)),
  );
}

/**
 * Identity for diffing samples. Rounded, so a window that drifts a subpixel does
 * not read as a new one and bury the window that actually appeared.
 */
export function windowKey(window: CgWindow): string {
  const { x, y, width, height } = window.bounds;
  return [
    window.ownerName,
    window.layer,
    Math.round(x),
    Math.round(y),
    Math.round(width),
    Math.round(height),
  ].join("|");
}
