import { PassThrough } from "node:stream";
import { describe, expect, it } from "vitest";
import { type Box, extractMouse, hitTest, MouseInput } from "./mouse";

describe("extractMouse", () => {
  const none = { presses: [], drags: [], releases: [], wheels: [], moves: [] };
  it.each([
    [
      "a left press between keys",
      "a\x1b[<0;12;3Mb",
      { keys: "ab", presses: [{ column: 12, row: 3 }] },
    ],
    ["a left release", "\x1b[<0;12;3m", { releases: [{ column: 12, row: 3 }] }],
    [
      "motion with the left button held",
      "\x1b[<32;9;4M",
      { drags: [{ column: 9, row: 4 }] },
    ],
    ["a right click", "\x1b[<2;5;5M\x1b[<2;5;5m", {}],
    ["motion with the right button held", "\x1b[<34;5;5M", {}],
    [
      "pointer motion with no button held",
      "\x1b[<35;7;4M",
      { moves: [{ column: 7, row: 4 }] },
    ],
    [
      "wheel up then down",
      "\x1b[<64;5;6M\x1b[<65;5;6M",
      {
        wheels: [
          { column: 5, row: 6, delta: -1 },
          { column: 5, row: 6, delta: 1 },
        ],
      },
    ],
    ["keys only", "hello\x1b[A", { keys: "hello\x1b[A" }],
  ])("strips %s", (_, text, expected) => {
    expect(extractMouse(text)).toEqual({ keys: "", ...none, ...expected });
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

  it("asks for the new background when the terminal turns light or dark, and hands on its reply instead of typing it", () => {
    const source = Object.assign(new PassThrough(), {
      isTTY: true,
      setRawMode: () => source,
    });
    let written = "";
    const stdout = Object.assign(new PassThrough(), { isTTY: true });
    stdout.on("data", (chunk) => {
      written += String(chunk);
    });
    const mouse = new MouseInput(
      source as unknown as NodeJS.ReadStream,
      stdout as unknown as NodeJS.WriteStream,
    );
    const keys: string[] = [];
    const backgrounds: string[] = [];
    mouse.events.on("keys", (text) => keys.push(text));
    mouse.events.on("background", (reply) => backgrounds.push(reply));

    source.write("a\x1b[?997;1n");
    source.write("\x1b]11;rgb:1e1e/1e1e/2020\x07b");

    expect(written).toContain("\x1b]11;?\x07");
    expect(backgrounds).toEqual(["\x1b]11;rgb:1e1e/1e1e/2020\x07"]);
    expect(keys).toEqual(["a", "b"]);
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
