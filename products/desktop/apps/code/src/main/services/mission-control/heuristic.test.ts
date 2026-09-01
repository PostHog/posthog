import { describe, expect, it } from "vitest";
import { detectMissionControl, windowKey } from "./heuristic";
import type { CgWindow, Rect } from "./window-list";

const DISPLAY: Rect = { x: 0, y: 0, width: 2560, height: 1440 };
const DISPLAYS = [DISPLAY];

const window = (partial: Partial<CgWindow>): CgWindow => ({
  ownerName: "PostHog",
  layer: 0,
  bounds: { x: 12, y: 38, width: 1281, height: 1410 },
  ...partial,
});

// Fixtures below come from a real dev.probeMissionControl recording.
const missionControlBacking = window({
  ownerName: "Dock",
  layer: 18,
  bounds: { x: 0, y: 0, width: 2560, height: 1440 },
});

const dockOwnWindow = window({
  ownerName: "Dock",
  layer: 20,
  bounds: { x: 0, y: 0, width: 2560, height: 1440 },
});

const dockStrip = window({
  ownerName: "Dock",
  layer: 20,
  bounds: { x: 1030, y: 1330, width: 500, height: 110 },
});

const dockBadge = window({
  ownerName: "Dock",
  layer: 17,
  bounds: { x: 1260, y: 840, width: 100, height: 109 },
});

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
      name: "the Dock's own full-display window",
      windows: [window({}), dockStrip, dockOwnWindow],
      expected: false,
    },
    {
      name: "the app switcher, which raises that same Dock window",
      windows: [dockOwnWindow],
      expected: false,
    },
    {
      name: "both Dock windows together",
      windows: [dockOwnWindow, missionControlBacking],
      expected: true,
    },
    {
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
    expect(detectMissionControl([missionControlBacking], [])).toBe(false);
  });
});

describe("windowKey", () => {
  it("ignores subpixel drift so a nudged window does not read as a new one", () => {
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
