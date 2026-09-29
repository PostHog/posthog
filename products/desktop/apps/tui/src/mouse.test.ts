import { PassThrough } from "node:stream";
import { describe, expect, it } from "vitest";
import { type Box, extractMouse, hitTest, MouseInput } from "./mouse";

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

describe("MouseInput", () => {
  it("still passes keys through when the terminal stream was paused before it started", async () => {
    const source = Object.assign(new PassThrough(), {
      isTTY: true,
      setRawMode: () => source,
    });
    const stdout = Object.assign(new PassThrough(), { isTTY: true });
    source.pause();

    const mouse = new MouseInput(
      source as unknown as NodeJS.ReadStream,
      stdout as unknown as NodeJS.WriteStream,
    );
    const received = new Promise<string>((resolve) =>
      mouse.stdin.once("data", (data) => resolve(String(data))),
    );
    source.write("a");

    expect(await received).toBe("a");
    mouse.dispose();
  });

  it("stops switching the real terminal's raw mode once disposed, so a reloaded copy keeps it", () => {
    const modes: boolean[] = [];
    const source = Object.assign(new PassThrough(), {
      isTTY: true,
      setRawMode: (mode: boolean) => {
        modes.push(mode);
        return source;
      },
    });
    const stdout = Object.assign(new PassThrough(), { isTTY: true });
    const mouse = new MouseInput(
      source as unknown as NodeJS.ReadStream,
      stdout as unknown as NodeJS.WriteStream,
    );

    mouse.stdin.setRawMode(true);
    mouse.dispose();
    mouse.stdin.setRawMode(false);

    expect(modes).toEqual([true]);
  });
});
