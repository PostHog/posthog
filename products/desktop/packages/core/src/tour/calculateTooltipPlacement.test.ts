import {
  calculateTooltipPlacement,
  type Rect,
} from "@posthog/core/tour/calculateTooltipPlacement";
import { describe, expect, it } from "vitest";

function rect(partial: Partial<Rect>): Rect {
  return {
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    width: 0,
    height: 0,
    ...partial,
  };
}

describe("calculateTooltipPlacement", () => {
  it("prefers the right side when there is room", () => {
    const target = rect({
      top: 100,
      left: 100,
      right: 150,
      bottom: 150,
      width: 50,
      height: 50,
    });
    const result = calculateTooltipPlacement(target, 200, 100, 1000, 800);
    expect(result.placement).toBe("right");
    expect(result.x).toBe(162);
  });

  it("falls back to left when right does not fit", () => {
    const target = rect({
      top: 100,
      left: 700,
      right: 950,
      bottom: 150,
      width: 250,
      height: 50,
    });
    const result = calculateTooltipPlacement(target, 200, 100, 1000, 800);
    expect(result.placement).toBe("left");
  });

  it("honours the preferred placement when it fits", () => {
    const target = rect({
      top: 400,
      left: 400,
      right: 450,
      bottom: 450,
      width: 50,
      height: 50,
    });
    const result = calculateTooltipPlacement(
      target,
      200,
      100,
      1000,
      800,
      "bottom",
    );
    expect(result.placement).toBe("bottom");
  });

  it("clamps within the viewport padding", () => {
    const target = rect({
      top: 0,
      left: 100,
      right: 150,
      bottom: 20,
      width: 50,
      height: 20,
    });
    const result = calculateTooltipPlacement(target, 200, 100, 1000, 800);
    expect(result.y).toBeGreaterThanOrEqual(8);
  });
});
