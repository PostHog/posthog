import { describe, expect, it } from "vitest";
import {
  computeGeometry,
  MENU_BAR_CLEARANCE,
  PILL_HEIGHT,
  PILL_TOP_TO_WINDOW_BOTTOM,
  PILL_TOP_TO_WINDOW_TOP,
  SCREEN_MARGIN,
} from "./geometry";

const AREA = { x: 0, y: 0, width: 1512, height: 950 };
const PILL = { width: 300, height: PILL_HEIGHT };

describe("computeGeometry", () => {
  it("anchors the window top at the pill and grows downward when there is room", () => {
    const geometry = computeGeometry(
      { x: 100, y: 200 },
      { width: 543, height: 600 },
      AREA,
      false,
    );
    expect(geometry).toMatchObject({
      x: 100,
      y: 200 - PILL_TOP_TO_WINDOW_TOP,
      width: 543,
      height: 600,
      flip: false,
    });
    expect(geometry.maxHeight).toBe(
      AREA.height - SCREEN_MARGIN - (200 - PILL_TOP_TO_WINDOW_TOP),
    );
  });

  it("flips upward when the content outgrows the room below a low anchor", () => {
    // The shipped bug: direction was decided at summon (pill-only content,
    // fits below), so an answer arriving later was crushed into the sliver.
    const anchor = { x: 100, y: 800 };
    const summoned = computeGeometry(anchor, PILL, AREA, false);
    expect(summoned.flip).toBe(false);

    const answered = computeGeometry(
      anchor,
      { width: 543, height: 500 },
      AREA,
      summoned.flip,
    );
    expect(answered.flip).toBe(true);
    // The pill keeps its on-screen position: window bottom sits just under it.
    expect(answered.y + answered.height).toBe(
      anchor.y + PILL_TOP_TO_WINDOW_BOTTOM,
    );
    expect(answered.height).toBe(500);
  });

  it("clamps to the roomier side when the content fits nowhere", () => {
    const anchor = { x: 100, y: 800 };
    const geometry = computeGeometry(
      anchor,
      { width: 543, height: 5000 },
      AREA,
      false,
    );
    expect(geometry.flip).toBe(true);
    const roomAbove = anchor.y + PILL_TOP_TO_WINDOW_BOTTOM - MENU_BAR_CLEARANCE;
    expect(geometry.height).toBe(roomAbove);
    expect(geometry.maxHeight).toBe(roomAbove);
    expect(geometry.y).toBe(anchor.y + PILL_TOP_TO_WINDOW_BOTTOM - roomAbove);
  });

  it("keeps the current direction while the content still fits there", () => {
    // No side-jumping mid-answer: shrinking content must not un-flip.
    const anchor = { x: 100, y: 500 };
    const geometry = computeGeometry(
      anchor,
      { width: 543, height: 300 },
      AREA,
      true,
    );
    expect(geometry.flip).toBe(true);
  });

  it("never reports less than pill height even with the anchor at the screen edge", () => {
    const geometry = computeGeometry(
      { x: 100, y: AREA.height - 20 },
      PILL,
      AREA,
      false,
    );
    expect(geometry.height).toBeGreaterThanOrEqual(PILL_HEIGHT);
    expect(geometry.maxHeight).toBeGreaterThanOrEqual(PILL_HEIGHT);
  });
});
