import type { DockWindowDump } from "./schemas";
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
 * undocumented and has no compatibility guarantee: validate it against a real
 * macOS release with `dev.dumpDockWindows` before trusting a change here.
 */
export function detectMissionControl(windows: CgWindow[]): boolean {
  return windows.some(
    (window) => window.ownerName === DOCK && Math.round(window.bounds.y) === -1,
  );
}

/**
 * Every Dock-owned window in a sample, for the dev-toolbar dump. Diffing a dump
 * taken with Mission Control open against one taken without is how the
 * predicate above gets confirmed or retuned.
 */
export function describeDockWindows(
  windows: CgWindow[],
): Omit<DockWindowDump, "available"> {
  return {
    detected: detectMissionControl(windows),
    windows: windows.filter((window) => window.ownerName === DOCK),
  };
}
