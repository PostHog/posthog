import { initTheme } from "@earendil-works/pi-coding-agent";
import { stripTerminalSequences } from "@earendil-works/pi-tui";
import { beforeAll, describe, expect, it } from "vitest";
import { Composer, isAppKey } from "./composer";

describe("isAppKey", () => {
  it.each([
    ["Tab", "\t", true],
    ["Shift+Tab", "\x1b[Z", true],
    ["legacy Ctrl+S", "\x13", true],
    ["kitty Cmd+Shift+S", "\x1b[115;10u", true],
    ["legacy Ctrl+\\", "\x1c", true],
    ["legacy Ctrl+C", "\x03", true],
    ["kitty Ctrl+D", "\x1b[100;5u", true],
    ["Page Up", "\x1b[5~", true],
    ["a letter", "h", false],
    ["Enter", "\r", false],
    ["Left", "\x1b[D", false],
    ["kitty Shift+Enter", "\x1b[13;2u", false],
  ])("%s", (_, sequence, expected) => {
    expect(isAppKey(sequence)).toBe(expected);
  });
});

describe("Composer", () => {
  beforeAll(() => initTheme("dark"));

  it("edits text with pi's editor and draws it without the hardware cursor marker", () => {
    let repaints = 0;
    const composer = new Composer(() => repaints++);
    for (const key of ["h", "e", "y", "\x1b[D", "!"]) composer.handleInput(key);

    const lines = composer.render(30, true);
    expect(lines.join("\n")).not.toContain("\x1b_pi:c");
    expect(lines.map((line) => stripTerminalSequences(line).trim())).toContain(
      "he!y",
    );
    expect(repaints).toBeGreaterThan(0);
  });
});
