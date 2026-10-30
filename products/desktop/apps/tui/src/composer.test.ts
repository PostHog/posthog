import { initTheme } from "@earendil-works/pi-coding-agent";
import { stripTerminalSequences } from "@earendil-works/pi-tui";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { Composer, isAppKey, isTyping } from "./composer";

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
    ["legacy Ctrl+N", "\x0e", true],
    ["legacy Ctrl+Q", "\x11", true],
    ["legacy Ctrl+R", "\x12", true],
    ["a letter", "h", false],
    ["Enter", "\r", false],
    ["Left", "\x1b[D", false],
    ["kitty Shift+Enter", "\x1b[13;2u", false],
  ])("%s", (_, sequence, expected) => {
    expect(isAppKey(sequence)).toBe(expected);
  });
});

describe("isTyping", () => {
  it.each([
    ["a letter", "h", true],
    ["a kitty-encoded letter", "\x1b[104u", true],
    ["a space", " ", true],
    ["a paste", "\x1b[200~hello\x1b[201~", true],
    ["an arrow", "\x1b[B", false],
    ["Enter", "\r", false],
    ["Escape", "\x1b", false],
    ["Tab", "\t", false],
  ])("%s", (_, sequence, expected) => {
    expect(isTyping(sequence)).toBe(expected);
  });
});

describe("Composer", () => {
  beforeAll(() => initTheme("dark"));

  it("edits text with pi's editor and draws it without the hardware cursor marker", () => {
    let repaints = 0;
    const composer = new Composer(
      () => repaints++,
      () => {},
    );
    for (const key of ["h", "e", "y", "\x1b[D", "!"]) composer.handleInput(key);

    const lines = composer.render(30, true).editor;
    expect(lines.join("\n")).not.toContain("\x1b_pi:c");
    expect(lines.map((line) => stripTerminalSequences(line).trim())).toContain(
      "he!y",
    );
    expect(repaints).toBeGreaterThan(0);
  });

  it("hands the text to submit on Enter, then clears", () => {
    const sent: string[] = [];
    const composer = new Composer(
      () => {},
      (text) => sent.push(text),
    );
    for (const key of ["h", "i", "\r"]) composer.handleInput(key);

    expect(sent).toEqual(["hi"]);
    expect(
      composer
        .render(30, true)
        .editor.map((line) => stripTerminalSequences(line).trim()),
    ).not.toContain("hi");
  });

  it("draws a rule above the input and none below", () => {
    const composer = new Composer(
      () => {},
      () => {},
    );
    composer.handleInput("x");
    const lines = composer
      .render(30, true)
      .editor.map((line) => stripTerminalSequences(line).trim());

    expect(lines[0]).toMatch(/^─+$/);
    expect(lines.slice(1).some((line) => /^─+$/.test(line))).toBe(false);
    expect(lines).toContain("x");
  });

  it("hands back slash suggestions apart from the input, so they can float over the chat", async () => {
    let repaints = 0;
    const composer = new Composer(
      () => repaints++,
      () => {},
    );
    composer.handleInput("/");
    await vi.waitFor(() =>
      expect(composer.render(40, true).popup.length).toBeGreaterThan(0),
    );

    const { editor, popup } = composer.render(40, true);
    const text = (lines: string[]) =>
      lines.map((line) => stripTerminalSequences(line)).join("\n");
    expect(text(popup)).toContain("model");
    expect(text(editor)).not.toContain("model");
    expect(text(editor)).toContain("/");
  });

  it("offers the run's own commands alongside the built-in ones", async () => {
    const composer = new Composer(
      () => {},
      () => {},
    );
    composer.setCommands([
      { name: "review-pr", description: "Review a pull request" },
    ]);
    composer.handleInput("/");
    await vi.waitFor(() =>
      expect(composer.render(60, true).popup.length).toBeGreaterThan(0),
    );

    const popup = composer
      .render(60, true)
      .popup.map((line) => stripTerminalSequences(line))
      .join("\n");
    expect(popup).toContain("review-pr");
    expect(popup).toContain("model");
  });

  it("draws the heaviest cursor in the focused pane and a grey one elsewhere", () => {
    const composer = new Composer(
      () => {},
      () => {},
    );
    composer.handleInput("x");
    const focused = composer.render(30, true).editor.join("");
    const unfocused = composer.render(30, false).editor.join("");

    expect(focused).toContain("\x1b[7m");
    expect(unfocused).not.toContain("\x1b[7m");
    expect(unfocused).toContain("\x1b[100m");
  });
});
