import { describe, expect, it } from "vitest";
import { faint } from "./faint";

describe("faint", () => {
  it("keeps a styled line faint through its own resets", () => {
    const line = "a\x1b[1mbold\x1b[22m b\x1b[0m c";
    expect(faint(line)).toBe(
      "\x1b[2ma\x1b[1mbold\x1b[22m\x1b[2m b\x1b[0m\x1b[2m c\x1b[22m",
    );
  });
});
