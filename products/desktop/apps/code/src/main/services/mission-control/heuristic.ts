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
 * macOS exposes no API — public or private — for "is Mission Control on screen
 * right now". The signal is that opening it makes the Dock process put up a
 * full-display backing window *between* the normal window level and the Dock's
 * own: layer 18 on macOS 26.
 *
 * Every part of that carries weight, and each was learned by getting it wrong:
 *
 *   - Matching on geometry alone fails, because the Dock's own window is also
 *     full-display. That made hovering the Dock, and the Cmd-Tab switcher, show
 *     the overlay — both bring the Dock's window on screen.
 *   - Excluding only layer 0 is not enough, for the same reason. The Dock's
 *     window sits at layer 20, so the range has to stop below it.
 *   - Requiring a layer above 0 keeps out the desktop wallpaper and the
 *     full-display Dock-owned window that also shows up at the normal level.
 *   - Requiring full-display coverage keeps out the Dock strip and the
 *     per-window badges Mission Control draws at layer 17.
 *
 * A 20-second `dev.probeMissionControl` recording covering Mission Control, an
 * app switch and two Dock hovers puts the layer-20 window in all four gestures
 * and the layer-18 window in Mission Control alone. This predicate matched only
 * the Mission Control interval, to the sample.
 *
 * Still undocumented, with no compatibility guarantee: an earlier revision keyed
 * off a y origin of -1, true on OS X 10.10 and false now. Re-check against a real
 * macOS release with the probe rather than adjusting it from first principles.
 *
 * App Exposé, Launchpad and Show Desktop are untested and may match. That is
 * harmless: each either hides our window completely or slides it off screen, so
 * the overlay is either invisible or a reasonable thing to show.
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
 * Identity for diffing one sample against another. CoreGraphics window numbers
 * are not in our window type, so owner plus layer plus rounded bounds stands in —
 * enough to tell a window that appeared from one that merely moved a subpixel.
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
