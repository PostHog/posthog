export type TerminalFont =
  | "berkeley-mono"
  | "jetbrains-mono"
  | "system"
  | "custom";

const FALLBACK =
  '"Berkeley Mono", "JetBrains Mono", "Consolas", "Monaco", monospace';

export const DEFAULT_TERMINAL_FONT_FAMILY = `"Berkeley Mono", ${FALLBACK}`;

export function resolveTerminalFontFamily(
  font: TerminalFont,
  customFontFamily: string,
): string {
  switch (font) {
    case "berkeley-mono":
      return DEFAULT_TERMINAL_FONT_FAMILY;
    case "jetbrains-mono":
      return `"JetBrains Mono", ${FALLBACK}`;
    case "system":
      return "ui-monospace, Menlo, Monaco, Consolas, monospace";
    case "custom": {
      const trimmed = customFontFamily.trim();
      return trimmed.length > 0 ? `${trimmed}, ${FALLBACK}` : FALLBACK;
    }
  }
}
