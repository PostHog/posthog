import type { CgWindow } from "./window-list";

const DOCK = "Dock";

/**
 * macOS exposes no API — public or private — for "is Mission Control on screen
 * right now". The one workable signal is that entering Mission Control makes
 * the Dock process put up a backing window that isn't there otherwise, sitting
 * one pixel above the top of the display.
 *
 * The Dock owns plenty of other windows (the Dock itself, Exposé leftovers,
 * Notification Center), so the y origin is what separates them. It is
 * undocumented and has no compatibility guarantee: check it against a real macOS
 * release with `dev.probeMissionControl` before trusting a change here.
 */
export function detectMissionControl(windows: CgWindow[]): boolean {
  return windows.some(
    (window) => window.ownerName === DOCK && Math.round(window.bounds.y) === -1,
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
