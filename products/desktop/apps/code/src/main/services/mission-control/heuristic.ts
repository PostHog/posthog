import type { CgWindow, Rect } from "./window-list";

const DOCK = "Dock";

// The Dock's own window level, historically NSDockWindowLevel. Its window
// spans the entire display, so this level must be excluded rather than matched.
const DOCK_WINDOW_LEVEL = 20;

// A window can sit a pixel outside the display it covers.
const COVERAGE_SLACK_PX = 2;

function coversDisplay(bounds: Rect, display: Rect): boolean {
  return (
    bounds.x <= display.x + COVERAGE_SLACK_PX &&
    bounds.y <= display.y + COVERAGE_SLACK_PX &&
    bounds.x + bounds.width >= display.x + display.width - COVERAGE_SLACK_PX &&
    bounds.y + bounds.height >= display.y + display.height - COVERAGE_SLACK_PX
  );
}

// macOS has no API for "is Mission Control on screen". The tell is that opening
// it makes the Dock put up a full-display window between the normal level and
// the Dock's own (layer 18 on macOS 26). The level bounds exclude the Dock's own
// full-display window (raised by Dock hover and Cmd-Tab too) and the desktop at
// layer 0; the coverage check excludes the Dock strip and the grid badges.
// Undocumented and version-specific: re-derive from a dev.probeMissionControl
// recording when a macOS release breaks it.
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

// Rounded so a window that drifts a subpixel between samples does not read as
// a new one.
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
