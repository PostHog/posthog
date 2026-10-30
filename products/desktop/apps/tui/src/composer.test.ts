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
      "❯ he!y",
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

  describe("prompt and shell mode", () => {
    const ORANGE = "\u001b[38;2;245;78;0m";
    const drawn = (composer: Composer, width = 30) => {
      const [rule, ...input] = composer.render(width, true).editor;
      return {
        rule,
        input,
        text: input.map((line) => stripTerminalSequences(line).trimEnd()),
      };
    };
    const typed = (keys: string[]) => {
      const sent: string[] = [];
      const composer = new Composer(
        () => {},
        (text) => sent.push(text),
      );
      for (const key of keys) composer.handleInput(key);
      return { composer, sent };
    };

    it("shows ❯ before the text and lines wrapped lines up under it", () => {
      const { composer } = typed([..."one two three four"]);
      const { text, rule } = drawn(composer, 12);

      expect(text[0].startsWith("❯ one")).toBe(true);
      expect(text[1].startsWith("  ")).toBe(true);
      expect(stripTerminalSequences(rule)).toBe("─".repeat(12));
      expect(rule).not.toContain(ORANGE);
    });

    it("turns ! in an empty composer into shell mode: an orange ! prompt and rule", () => {
      const { composer, sent } = typed(["!", "l", "s"]);
      const { text, rule, input } = drawn(composer);

      expect(composer.isShellCommand()).toBe(true);
      expect(text[0].startsWith("! ls")).toBe(true);
      expect(input[0].startsWith(`${ORANGE}!`)).toBe(true);
      expect(rule).toContain(ORANGE);

      composer.handleInput("\r");
      expect(sent).toEqual(["!ls"]);
      expect(composer.isShellCommand()).toBe(false);
      expect(drawn(composer).text[0].startsWith("❯")).toBe(true);
    });

    it.each([
      ["Backspace in an empty shell command", ["!", "\x7f"]],
      ["Backspace after deleting the command", ["!", "l", "\x7f", "\x7f"]],
    ])("leaves shell mode on %s", (_, keys) => {
      const { composer } = typed(keys);
      const { text, rule } = drawn(composer);

      expect(composer.isShellCommand()).toBe(false);
      expect(text[0].startsWith("❯")).toBe(true);
      expect(rule).not.toContain(ORANGE);
    });

    it("keeps shell mode while the command still has text to delete", () => {
      const { composer } = typed(["!", "l", "s", "\x7f"]);
      expect(composer.isShellCommand()).toBe(true);
      expect(drawn(composer).text[0].startsWith("! l")).toBe(true);
    });

    it("treats ! after other text as text", () => {
      const { composer } = typed(["a", "!"]);
      expect(composer.isShellCommand()).toBe(false);
      expect(drawn(composer).text[0].startsWith("❯ a!")).toBe(true);
    });

    it("opens shell mode for text put back with a leading !, and leaves it on clear", () => {
      const { composer } = typed([]);
      composer.setText("!ls");
      expect(composer.isShellCommand()).toBe(true);
      expect(drawn(composer).text[0].startsWith("! ls")).toBe(true);

      composer.clear();
      expect(composer.isShellCommand()).toBe(false);
      expect(drawn(composer).text[0].startsWith("❯")).toBe(true);
    });
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
    expect(lines).toContain("❯ x");
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
    const suggestionsFor = async (typed: string): Promise<string> => {
      composer.clear();
      for (const key of typed) composer.handleInput(key);
      await vi.waitFor(() =>
        expect(composer.render(60, true).popup.length).toBeGreaterThan(0),
      );
      return composer
        .render(60, true)
        .popup.map((line) => stripTerminalSequences(line))
        .join("\n");
    };

    expect(await suggestionsFor("/re")).toContain("review-pr");
    expect(await suggestionsFor("/mo")).toContain("model");
  });

  it("shows a cursor only while its pane has focus", () => {
    const composer = new Composer(
      () => {},
      () => {},
    );
    composer.handleInput("x");

    expect(composer.render(30, true).editor.join("")).toContain("\x1b[7m");
    expect(composer.render(30, false).editor.join("")).not.toContain("\x1b[7m");
  });

  it("reports while its suggestion list is open", async () => {
    const composer = new Composer(
      () => {},
      () => {},
    );
    expect(composer.showingSuggestions()).toBe(false);
    composer.handleInput("/");
    await vi.waitFor(() => expect(composer.showingSuggestions()).toBe(true));
  });
});
