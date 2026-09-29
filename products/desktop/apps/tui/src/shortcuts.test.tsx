import { type Key, useInput } from "ink";
import { describe, expect, it } from "vitest";
import { DoublePress, type Shortcut, shortcutFor } from "./shortcuts";
import { renderInTerminal } from "./testing";

// Feeds raw terminal bytes through a real Ink instance and reports the shortcut they map to.
async function shortcutFromBytes(bytes: string): Promise<Shortcut | null> {
  const seen: Array<Shortcut | null> = [];
  function Probe(): null {
    useInput((input: string, key: Key) => seen.push(shortcutFor(input, key)));
    return null;
  }
  const { instance, type } = renderInTerminal(<Probe />);
  await new Promise((resolve) => setTimeout(resolve, 10));
  type(bytes);
  await new Promise((resolve) => setTimeout(resolve, 30));
  instance.unmount();
  return seen[0] ?? null;
}

describe("shortcutFor", () => {
  it.each([
    ["legacy Ctrl+S", "\x13", "splitRight"],
    ["kitty Ctrl+S", "\x1b[115;5u", "splitRight"],
    ["kitty Cmd+S", "\x1b[115;9u", "splitRight"],
    ["kitty Ctrl+Shift+S", "\x1b[115;6u", "splitDown"],
    ["kitty Cmd+Shift+S", "\x1b[115;10u", "splitDown"],
    ["legacy Ctrl+\\ fallback", "\x1c", "splitDown"],
    ["kitty Ctrl+\\ fallback", "\x1b[92;5u", "splitDown"],
    ["legacy Ctrl+C", "\x03", "close"],
    ["kitty Ctrl+C", "\x1b[99;5u", "close"],
    ["legacy Ctrl+D", "\x04", "close"],
    ["legacy Ctrl+N", "\x0e", "newChat"],
    ["legacy Ctrl+Q", "\x11", "quit"],
    ["legacy Ctrl+R", "\x12", "reload"],
    ["kitty Ctrl+R", "\x1b[114;5u", "reload"],
    ["kitty Ctrl+Q", "\x1b[113;5u", "quit"],
    ["kitty Ctrl+N", "\x1b[110;5u", "newChat"],
    ["plain s", "s", null],
    ["Tab", "\t", null],
  ])("%s", async (_, bytes, expected) => {
    expect(await shortcutFromBytes(bytes)).toBe(expected);
  });
});

describe("DoublePress", () => {
  it.each([
    ["a single press only arms", [0], [false]],
    ["a second press inside the window confirms", [0, 900], [false, true]],
    [
      "a second press after the window re-arms",
      [0, 1100, 1500],
      [false, false, true],
    ],
    ["a confirmed pair resets", [0, 100, 200], [false, true, false]],
  ])("%s", (_, times, expected) => {
    const guard = new DoublePress(1000);
    expect(times.map((now) => guard.press(now))).toEqual(expected);
  });
});
