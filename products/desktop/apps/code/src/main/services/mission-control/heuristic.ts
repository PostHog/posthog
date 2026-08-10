import type { CgWindow, Rect } from "./window-list";

const DOCK = "Dock";

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
 * right now". The workable signal is that opening it makes the Dock process put
 * up full-display backing windows above the normal window level, which are not
 * there otherwise. On macOS 26 there are two, at layers 18 and 20.
 *
 * Both halves of the test carry weight. The Dock owns plenty of other windows —
 * the Dock strip itself, the per-window badges Mission Control draws at layer 17,
 * and a full-display window at layer 0 — so size alone and layer alone each match
 * things that are not Mission Control. Requiring a layer above the normal window
 * level also keeps the desktop wallpaper, which the Dock draws far below it, out.
 *
 * This is undocumented and has no compatibility guarantee. An earlier revision
 * keyed off a y origin of -1, which held on OS X 10.10 and does not now. Re-check
 * it against a real macOS release with `dev.probeMissionControl` rather than
 * adjusting it from first principles.
 *
 * App Exposé, Launchpad and Show Desktop put up similar Dock windows and so match
 * too. That is harmless: each either hides our window completely or slides it off
 * screen, so the overlay is either invisible or a reasonable thing to show.
 */
export function detectMissionControl(
  windows: CgWindow[],
  displays: Rect[],
): boolean {
  return windows.some(
    (window) =>
      window.ownerName === DOCK &&
      window.layer > 0 &&
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
