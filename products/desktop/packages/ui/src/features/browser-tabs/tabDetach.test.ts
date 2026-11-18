import type { DragOperation } from "@dnd-kit/abstract";
import { describe, expect, it } from "vitest";
import { DETACH_DISTANCE, DetachFromStrip } from "./tabDetach";

function apply(transform: { x: number; y: number }): { x: number; y: number } {
  const modifier = new DetachFromStrip({} as never);
  return modifier.apply({ transform } as DragOperation);
}

describe("DetachFromStrip", () => {
  it.each([
    { y: 0, expected: 0 },
    { y: DETACH_DISTANCE - 1, expected: 0 },
    { y: -(DETACH_DISTANCE - 1), expected: 0 },
    { y: DETACH_DISTANCE, expected: DETACH_DISTANCE },
    { y: -DETACH_DISTANCE, expected: -DETACH_DISTANCE },
    { y: 120, expected: 120 },
  ])("keeps x and maps y=$y to $expected", ({ y, expected }) => {
    expect(apply({ x: 37, y })).toEqual({ x: 37, y: expected });
  });
});
