import { describe, expect, it } from "vitest";
import { themeFromBackgroundReply } from "./theme";

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
