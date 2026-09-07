import { describe, expect, it } from "vitest";
import {
  DEFAULT_TERMINAL_FONT_FAMILY,
  resolveTerminalFontFamily,
} from "./resolveTerminalFontFamily";

const FALLBACK =
  '"Berkeley Mono", "JetBrains Mono", "Consolas", "Monaco", monospace';

describe("resolveTerminalFontFamily", () => {
  it("exports a default that matches the berkeley-mono stack", () => {
    expect(DEFAULT_TERMINAL_FONT_FAMILY).toBe(`"Berkeley Mono", ${FALLBACK}`);
  });

  it.each([
    {
      font: "berkeley-mono" as const,
      custom: "",
      expected: `"Berkeley Mono", ${FALLBACK}`,
    },
    {
      font: "jetbrains-mono" as const,
      custom: "",
      expected: `"JetBrains Mono", ${FALLBACK}`,
    },
    {
      font: "system" as const,
      custom: "Fira Code",
      expected: "ui-monospace, Menlo, Monaco, Consolas, monospace",
    },
  ])("resolves the $font preset", ({ font, custom, expected }) => {
    expect(resolveTerminalFontFamily(font, custom)).toBe(expected);
  });

  it("falls back to the default stack when custom is empty or whitespace", () => {
    expect(resolveTerminalFontFamily("custom", "")).toBe(FALLBACK);
    expect(resolveTerminalFontFamily("custom", "   ")).toBe(FALLBACK);
  });

  it("prepends a trimmed custom value to the fallback stack", () => {
    expect(resolveTerminalFontFamily("custom", "Fira Code")).toBe(
      `Fira Code, ${FALLBACK}`,
    );
    expect(resolveTerminalFontFamily("custom", "  Fira Code  ")).toBe(
      `Fira Code, ${FALLBACK}`,
    );
  });

  it("preserves multi-value font stacks the user types verbatim", () => {
    expect(
      resolveTerminalFontFamily("custom", '"Cascadia Code", "Fira Code"'),
    ).toBe(`"Cascadia Code", "Fira Code", ${FALLBACK}`);
  });
});
