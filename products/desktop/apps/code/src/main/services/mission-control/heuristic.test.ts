import { describe, expect, it } from "vitest";
import { detectMissionControl, windowKey } from "./heuristic";
import type { CgWindow, Rect } from "./window-list";

/** One 2560x1440 display, matching the machine the fixtures were captured on. */
const DISPLAY: Rect = { x: 0, y: 0, width: 2560, height: 1440 };
const DISPLAYS = [DISPLAY];

const window = (partial: Partial<CgWindow>): CgWindow => ({
  ownerName: "PostHog",
  layer: 0,
  bounds: { x: 12, y: 38, width: 1281, height: 1410 },
  ...partial,
});

/**
 * The full-display Dock window Mission Control puts up, from a real
 * dev.probeMissionControl recording. Layer 18: below the Dock's own level.
 */
const missionControlBacking = window({
  ownerName: "Dock",
  layer: 18,
  bounds: { x: 0, y: 0, width: 2560, height: 1440 },
});

/**
 * The Dock's own window, which also spans the whole display. In the same
 * recording it was present for Mission Control, the Cmd-Tab switcher and both
 * Dock hovers, so it identifies the Dock drawing, not Mission Control.
 */
const dockOwnWindow = window({
  ownerName: "Dock",
  layer: 20,
  bounds: { x: 0, y: 0, width: 2560, height: 1440 },
});

/** The visible Dock strip. */
const dockStrip = window({
  ownerName: "Dock",
  layer: 20,
  bounds: { x: 1030, y: 1330, width: 500, height: 110 },
});

/** A per-window badge the Dock draws inside the Mission Control grid. */
const dockBadge = window({
  ownerName: "Dock",
  layer: 17,
  bounds: { x: 1260, y: 840, width: 100, height: 109 },
});

/** Full-display and Dock-owned, but at the normal window level. */
const dockAtNormalLayer = window({
  ownerName: "Dock",
  layer: 0,
  bounds: { x: 0, y: 0, width: 2560, height: 1440 },
});

describe("detectMissionControl", () => {
  it.each([
    { name: "an empty sample", windows: [], expected: false },
    {
      name: "an ordinary desktop",
      windows: [window({}), dockStrip],
      expected: false,
    },
    {
      name: "Mission Control's layer 18 backing window",
      windows: [window({}), dockStrip, missionControlBacking],
      expected: true,
    },
    {
      // Regression: hovering the Dock brings this window on screen, and it used
      // to show the overlay. It is the Dock itself, at the Dock's own level.
      name: "the Dock's own full-display window",
      windows: [window({}), dockStrip, dockOwnWindow],
      expected: false,
    },
    {
      // Regression: the Cmd-Tab switcher brings the same window on screen.
      name: "the app switcher, which raises that same Dock window",
      windows: [dockOwnWindow],
      expected: false,
    },
    {
      // Mission Control raises both, so the Dock's own window must not mask the
      // one that actually means something.
      name: "both Dock windows together",
      windows: [dockOwnWindow, missionControlBacking],
      expected: true,
    },
    {
      // The Dock strip is full-width but not full-height. Dropping the coverage
      // test for a bare owner check would pin the overlay on permanently.
      name: "the Dock strip alone",
      windows: [dockStrip],
      expected: false,
    },
    {
      name: "the grid badges alone",
      windows: [dockBadge, dockBadge],
      expected: false,
    },
    {
      // Layer 0 is where ordinary windows and the desktop live, so a full-display
      // Dock window there is not evidence of anything.
      name: "a full-display Dock window at layer 0",
      windows: [dockAtNormalLayer],
      expected: false,
    },
    {
      name: "a full-display window owned by another app",
      windows: [
        window({
          layer: 18,
          bounds: { x: 0, y: 0, width: 2560, height: 1440 },
        }),
      ],
      expected: false,
    },
    {
      // The OS X 10.10 shape, which sat a pixel above the display and overhung it.
      name: "a backing window that overhangs the display",
      windows: [
        window({
          ownerName: "Dock",
          layer: 18,
          bounds: { x: 0, y: -1, width: 2560, height: 1441 },
        }),
      ],
      expected: true,
    },
  ])("is $expected for $name", ({ windows, expected }) => {
    expect(detectMissionControl(windows, DISPLAYS)).toBe(expected);
  });

  it("matches a backing window on a secondary display", () => {
    const secondary: Rect = { x: 2560, y: 0, width: 1920, height: 1080 };

    expect(
      detectMissionControl(
        [
          window({
            ownerName: "Dock",
            layer: 18,
            bounds: secondary,
          }),
        ],
        [DISPLAY, secondary],
      ),
    ).toBe(true);
  });

  it("does not match when no display is known", () => {
    // getAllDisplays() coming back empty must not be read as full coverage.
    expect(detectMissionControl([missionControlBacking], [])).toBe(false);
  });
});

describe("windowKey", () => {
  it("ignores subpixel drift so a nudged window does not read as a new one", () => {
    // The probe diffs samples by this key; without rounding, a window that
    // shifts a fraction of a pixel between samples would be reported as having
    // appeared, burying the one window that actually did.
    expect(
      windowKey(
        window({ bounds: { x: 0.4, y: -1.2, width: 1440.1, height: 900.9 } }),
      ),
    ).toBe(
      windowKey(window({ bounds: { x: 0, y: -1, width: 1440, height: 901 } })),
    );
  });

  it("separates windows that differ by owner", () => {
    expect(windowKey(dockStrip)).not.toBe(
      windowKey({ ...dockStrip, ownerName: "Finder" }),
    );
  });
});
