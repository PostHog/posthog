import { describe, expect, it } from "vitest";
import { Gesture, wordAt } from "./selection";

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

  it("reads a second click on the same cell straight after as a word pick, and a late one as a click", () => {
    const gesture = new Gesture();
    gesture.press(at(5, 3));
    gesture.release(at(5, 3), 1_000);
    gesture.press(at(5, 3));
    expect(gesture.release(at(5, 3), 1_300)).toEqual({
      kind: "word",
      at: at(5, 3),
    });
    gesture.press(at(5, 3));
    expect(gesture.release(at(5, 3), 1_500)).toEqual({
      kind: "click",
      at: at(5, 3),
    });
    gesture.press(at(5, 3));
    expect(gesture.release(at(5, 3), 2_500)).toEqual({
      kind: "click",
      at: at(5, 3),
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

describe("wordAt", () => {
  it.each([
    ["inside a word", 7, { start: 6, end: 11 }],
    ["on a word's first letter", 0, { start: 0, end: 5 }],
    ["on a space", 5, null],
    ["past the end", 20, null],
  ])("finds the word %s", (_, column, expected) => {
    expect(wordAt("hello world", column)).toEqual(expected);
  });
});
