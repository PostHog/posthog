import { describe, expect, it } from "vitest";
import {
  SWIPE_COMMIT_THRESHOLD,
  SWIPE_INTENT_THRESHOLD,
  type SwipeIntent,
  stampOpacity,
  stampOpacityRange,
} from "./swipeIntent";

/** What `Animated.Value.interpolate` does with a two-point clamped range. */
function interpolate(range: ReturnType<typeof stampOpacityRange>, x: number) {
  const [inLow, inHigh] = range.inputRange as [number, number];
  const [outLow, outHigh] = range.outputRange as [number, number];
  if (x <= inLow) return outLow;
  if (x >= inHigh) return outHigh;
  return outLow + ((x - inLow) / (inHigh - inLow)) * (outHigh - outLow);
}

describe("stampOpacity", () => {
  it.each<[SwipeIntent, number]>([
    ["accept", 1],
    ["dismiss", -1],
  ])("stays hidden below the intent threshold when %s", (intent, sign) => {
    expect(stampOpacity(0, intent)).toBe(0);
    expect(stampOpacity(sign * 10, intent)).toBe(0);
    expect(stampOpacity(sign * SWIPE_INTENT_THRESHOLD, intent)).toBe(0);
  });

  it.each<[SwipeIntent, number]>([
    ["accept", 1],
    ["dismiss", -1],
  ])("reaches full opacity where the swipe commits when %s", (intent, sign) => {
    expect(stampOpacity(sign * SWIPE_COMMIT_THRESHOLD, intent)).toBe(1);
    // Past the commit point it clamps rather than overshooting.
    expect(stampOpacity(sign * 400, intent)).toBe(1);
  });

  it("ramps linearly between the two thresholds", () => {
    const midpoint = (SWIPE_INTENT_THRESHOLD + SWIPE_COMMIT_THRESHOLD) / 2;
    expect(stampOpacity(midpoint, "accept")).toBeCloseTo(0.5, 10);
    expect(stampOpacity(-midpoint, "dismiss")).toBeCloseTo(0.5, 10);
  });

  it.each<[SwipeIntent, number]>([
    ["accept", -1],
    ["dismiss", 1],
  ])("stays hidden while dragging away from %s", (intent, sign) => {
    expect(stampOpacity(sign * SWIPE_COMMIT_THRESHOLD, intent)).toBe(0);
  });
});

describe("stampOpacityRange", () => {
  // The card animates opacity off the native driver, so the interpolation is
  // what users actually see — it has to match the helper the tests describe.
  it.each<SwipeIntent>(["accept", "dismiss"])(
    "matches stampOpacity across the drag range for %s",
    (intent) => {
      const range = stampOpacityRange(intent);
      for (let dx = -300; dx <= 300; dx += 5) {
        expect(interpolate(range, dx)).toBeCloseTo(
          stampOpacity(dx, intent),
          10,
        );
      }
    },
  );
});
