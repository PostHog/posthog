import { describe, expect, it } from "vitest";
import { Gesture } from "./selection";

const at = (column: number, row: number) => ({ column, row });

describe("Gesture", () => {
  it("reads a press and release on one cell as a click", () => {
    const gesture = new Gesture();
    gesture.press(at(5, 3));
    expect(gesture.release(at(5, 3))).toEqual({ kind: "click", at: at(5, 3) });
  });

  it("reads a drag to another cell as a selection, from the press to the pointer", () => {
    const gesture = new Gesture();
    gesture.press(at(5, 3));
    expect(gesture.drag(at(9, 3))).toEqual({ from: at(5, 3), to: at(9, 3) });
    expect(gesture.drag(at(2, 6))).toEqual({ from: at(5, 3), to: at(2, 6) });
    expect(gesture.release(at(2, 6))).toEqual({
      kind: "select",
      from: at(5, 3),
      to: at(2, 6),
    });
  });

  it("stays a selection when the drag comes back to the press cell", () => {
    const gesture = new Gesture();
    gesture.press(at(5, 3));
    gesture.drag(at(8, 3));
    expect(gesture.release(at(5, 3))).toEqual({
      kind: "select",
      from: at(5, 3),
      to: at(5, 3),
    });
  });

  it("ignores a drag or release with no press before it", () => {
    const gesture = new Gesture();
    expect(gesture.drag(at(1, 1))).toBeNull();
    expect(gesture.release(at(1, 1))).toBeNull();
    gesture.press(at(1, 1));
    gesture.release(at(1, 1));
    expect(gesture.release(at(1, 1))).toBeNull();
  });
});
