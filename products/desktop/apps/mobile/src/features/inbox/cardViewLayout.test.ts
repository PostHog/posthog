import { describe, expect, it } from "vitest";
import {
  inboxCardViewBottomInset,
  inboxHeaderFadeHeight,
  VIEW_TOGGLE_BOTTOM_GAP,
} from "./cardViewLayout";

describe("inboxHeaderFadeHeight", () => {
  it.each([
    ["notch device", 59, 139],
    ["flat-top device", 20, 100],
    ["no inset", 0, 80],
  ])("clears the whole fade on a %s", (_name, insetTop, expected) => {
    expect(inboxHeaderFadeHeight(insetTop)).toBe(expected);
  });

  it("leaves more room than the scrolling views' content inset", () => {
    // The list and archive views pad by `insets.top + 60`, which only clears
    // the header controls. A static card has to clear the gradient too.
    const insetTop = 59;
    expect(inboxHeaderFadeHeight(insetTop)).toBeGreaterThan(insetTop + 60);
  });
});

describe("inboxCardViewBottomInset", () => {
  it.each([
    ["home-indicator device", 34, 106],
    ["button device", 0, 72],
  ])("clears the toggle pill on a %s", (_name, insetBottom, expected) => {
    expect(inboxCardViewBottomInset(insetBottom)).toBe(expected);
  });

  it("clears the top of the pill, not just its bottom gap", () => {
    // The pill floats at `insets.bottom + VIEW_TOGGLE_BOTTOM_GAP` and is 44pt
    // tall, so the hint row above it has to start beyond both.
    const insetBottom = 34;
    const pillTop = insetBottom + VIEW_TOGGLE_BOTTOM_GAP + 44;
    expect(inboxCardViewBottomInset(insetBottom)).toBeGreaterThan(pillTop);
  });
});
