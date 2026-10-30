import { describe, expect, it } from "vitest";
import { type Box, extractMouse, hitTest } from "./mouse";

describe("extractMouse", () => {
  it.each([
    [
      "a left press between keys",
      "a\x1b[<0;12;3Mb",
      "ab",
      [{ column: 12, row: 3 }],
      [],
    ],
    ["a release", "\x1b[<0;12;3m", "", [], []],
    ["a right click", "\x1b[<2;5;5M", "", [], []],
    [
      "wheel up then down",
      "\x1b[<64;5;6M\x1b[<65;5;6M",
      "",
      [],
      [
        { column: 5, row: 6, delta: -1 },
        { column: 5, row: 6, delta: 1 },
      ],
    ],
    ["keys only", "hello\x1b[A", "hello\x1b[A", [], []],
  ])("strips %s", (_, text, keys, clicks, wheels) => {
    expect(extractMouse(text)).toEqual({ keys, clicks, wheels });
  });
});

describe("hitTest", () => {
  const boxes: Array<[string, Box]> = [
    ["sidebar", { left: 1, top: 1, right: 32, bottom: 24 }],
    ["pane", { left: 33, top: 1, right: 80, bottom: 24 }],
  ];

  it.each([
    [{ column: 32, row: 10 }, "sidebar"],
    [{ column: 33, row: 10 }, "pane"],
    [{ column: 81, row: 10 }, null],
  ])("finds the box under %o", (click, expected) => {
    expect(hitTest(click, boxes)?.[0] ?? null).toBe(expected);
  });
});
