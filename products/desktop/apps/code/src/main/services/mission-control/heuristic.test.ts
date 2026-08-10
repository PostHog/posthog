import { describe, expect, it } from "vitest";
import { describeDockWindows, detectMissionControl } from "./heuristic";
import type { CgWindow } from "./window-list";

const window = (partial: Partial<CgWindow>): CgWindow => ({
  ownerName: "PostHog",
  layer: 0,
  bounds: { x: 0, y: 0, width: 1440, height: 900 },
  ...partial,
});

/** The window Mission Control puts up: Dock-owned, one pixel above the top. */
const missionControlBacking = window({
  ownerName: "Dock",
  layer: 20,
  bounds: { x: 0, y: -1, width: 1440, height: 901 },
});

/** The Dock's own strip, which is present whether or not Mission Control is. */
const dockStrip = window({
  ownerName: "Dock",
  layer: 20,
  bounds: { x: 0, y: 830, width: 1440, height: 70 },
});

const menuBar = window({
  ownerName: "Window Server",
  layer: 25,
  bounds: { x: 0, y: 0, width: 1440, height: 24 },
});

describe("detectMissionControl", () => {
  it.each([
    { name: "an empty sample", windows: [], expected: false },
    {
      name: "an ordinary desktop",
      windows: [window({}), dockStrip, menuBar],
      expected: false,
    },
    {
      name: "Mission Control open",
      windows: [window({}), dockStrip, missionControlBacking, menuBar],
      expected: true,
    },
    {
      // Whatever else is on screen at y=-1, only the Dock's copy counts —
      // otherwise a window nudged above the menu bar would trip the overlay.
      name: "a non-Dock window at the same origin",
      windows: [window({ bounds: { x: 0, y: -1, width: 1440, height: 901 } })],
      expected: false,
    },
    {
      // A scaled display reports fractional origins, so the predicate rounds.
      name: "a fractional y origin",
      windows: [
        window({
          ownerName: "Dock",
          bounds: { x: 0, y: -1.0000001, width: 1440, height: 901 },
        }),
      ],
      expected: true,
    },
  ])("is $expected for $name", ({ windows, expected }) => {
    expect(detectMissionControl(windows)).toBe(expected);
  });
});

describe("describeDockWindows", () => {
  it("keeps only Dock-owned windows, with the verdict for the sample", () => {
    expect(
      describeDockWindows([window({}), dockStrip, missionControlBacking]),
    ).toEqual({
      detected: true,
      windows: [dockStrip, missionControlBacking],
    });
  });
});
