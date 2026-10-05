import { describe, expect, it } from "vitest";
import {
  applyBackground,
  selectionBackground,
  themeFromBackgroundReply,
  userMessageBackground,
} from "./theme";

describe("themeFromBackgroundReply", () => {
  it.each([
    ["a white background", "\x1b]11;rgb:ffff/ffff/ffff\x07", "light"],
    [
      "a near-black background ended with ST",
      "\x1b]11;rgb:1e1e/1e1e/2020\x1b\\",
      "dark",
    ],
    ["two-digit channels", "\x1b]11;rgb:fa/fa/fa\x07", "light"],
    ["no reply", "", null],
  ])("reads %s", (_, reply, expected) => {
    expect(themeFromBackgroundReply(reply)).toBe(expected);
  });
});

describe("fills", () => {
  const channels = (fill: string): number[] =>
    fill.startsWith("#")
      ? [1, 3, 5].map((at) => Number.parseInt(fill.slice(at, at + 2), 16))
      : (fill
          .match(/48;2;(\d+);(\d+);(\d+)m/)
          ?.slice(1)
          .map(Number) ?? []);

  it.each([
    ["a dark background", [30, 30, 40], "lighter"],
    ["a light background", [250, 250, 245], "darker"],
  ] as const)(
    "step off %s, %s, the selection further than a message",
    (_, background, direction) => {
      applyBackground([...background]);
      const message = channels(userMessageBackground());
      const selection = channels(selectionBackground());
      const sign = direction === "lighter" ? 1 : -1;

      expect(
        message.every((value, at) => sign * (value - background[at]) > 0),
      ).toBe(true);
      expect(
        selection.every((value, at) => sign * (value - message[at]) > 0),
      ).toBe(true);
    },
  );
});
