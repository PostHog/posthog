import type { McpUiStyles } from "@modelcontextprotocol/ext-apps/app-bridge";

// The app runs in a WebView, so it needs literal colours rather than our
// DynamicColorIOS tokens; these mirror the theme's light and dark values.
const PALETTES = {
  light: {
    bg: "#EEEFE9",
    surface: "#FFFFFF",
    raised: "#F7F7F3",
    ink: "#151515",
    inkSoft: "#4F5150",
    inkMute: "#8F918D",
    line: "#DCDDD6",
    lineSoft: "#E7E8E1",
  },
  dark: {
    bg: "#151515",
    surface: "#222222",
    raised: "#1C1C1C",
    ink: "#EEEFE9",
    inkSoft: "#B8BAB4",
    inkMute: "#7C7E7A",
    line: "#333333",
    lineSoft: "#2A2A2A",
  },
};

const ACCENT = "#F54E00";
const DANGER = "#FF474D";
const OK = "#36C46F";
const WARN = "#F9BD2B";

export function buildHostStyles(dark: boolean): {
  variables: McpUiStyles;
  css: { fonts: string };
} {
  const c = dark ? PALETTES.dark : PALETTES.light;
  const variables: Record<string, string> = {
    "--color-background-primary": c.bg,
    "--color-background-secondary": c.surface,
    "--color-background-tertiary": c.raised,
    "--color-background-inverse": c.ink,
    "--color-background-ghost": "transparent",
    "--color-background-info": dark ? "#2A1A10" : "#FFEFE6",
    "--color-background-danger": dark ? "#3b0d0d" : "#fde8e8",
    "--color-background-success": dark ? "#0f2d18" : "#dcfce7",
    "--color-background-warning": dark ? "#3a2c00" : "#fef3c7",
    "--color-background-disabled": c.raised,
    "--color-text-primary": c.ink,
    "--color-text-secondary": c.inkSoft,
    "--color-text-tertiary": c.inkMute,
    "--color-text-inverse": c.bg,
    "--color-text-ghost": c.inkMute,
    "--color-text-info": ACCENT,
    "--color-text-danger": DANGER,
    "--color-text-success": OK,
    "--color-text-warning": WARN,
    "--color-text-disabled": c.inkMute,
    "--color-border-primary": c.line,
    "--color-border-secondary": c.lineSoft,
    "--color-border-tertiary": c.lineSoft,
    "--color-border-inverse": c.ink,
    "--color-border-ghost": "transparent",
    "--color-border-info": ACCENT,
    "--color-border-danger": DANGER,
    "--color-border-success": OK,
    "--color-border-warning": WARN,
    "--color-border-disabled": c.lineSoft,
    "--color-ring-primary": ACCENT,
    "--color-ring-secondary": c.line,
    "--color-ring-inverse": c.bg,
    "--color-ring-info": ACCENT,
    "--color-ring-danger": DANGER,
    "--color-ring-success": OK,
    "--color-ring-warning": WARN,
    "--font-sans": "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    "--font-mono": "ui-monospace, 'JetBrains Mono', 'SF Mono', monospace",
    "--font-weight-normal": "400",
    "--font-weight-medium": "500",
    "--font-weight-semibold": "600",
    "--font-weight-bold": "700",
    "--font-text-xs-size": "12px",
    "--font-text-sm-size": "14px",
    "--font-text-md-size": "16px",
    "--font-text-lg-size": "18px",
    "--font-heading-xs-size": "18px",
    "--font-heading-sm-size": "20px",
    "--font-heading-md-size": "24px",
    "--font-heading-lg-size": "28px",
    "--font-heading-xl-size": "32px",
    "--font-heading-2xl-size": "48px",
    "--font-heading-3xl-size": "60px",
    "--font-text-xs-line-height": "1.5",
    "--font-text-sm-line-height": "1.5",
    "--font-text-md-line-height": "1.5",
    "--font-text-lg-line-height": "1.5",
    "--font-heading-xs-line-height": "1.3",
    "--font-heading-sm-line-height": "1.3",
    "--font-heading-md-line-height": "1.25",
    "--font-heading-lg-line-height": "1.25",
    "--font-heading-xl-line-height": "1.2",
    "--font-heading-2xl-line-height": "1.2",
    "--font-heading-3xl-line-height": "1.1",
    "--border-radius-xs": "4px",
    "--border-radius-sm": "8px",
    "--border-radius-md": "12px",
    "--border-radius-lg": "16px",
    "--border-radius-xl": "24px",
    "--border-radius-full": "9999px",
    "--border-width-regular": "1px",
    "--shadow-hairline": `0 0 0 1px ${c.line}`,
    "--shadow-sm": "0 1px 2px rgba(0,0,0,0.05)",
    "--shadow-md": "0 4px 6px -1px rgba(0,0,0,0.1)",
    "--shadow-lg": "0 10px 15px -3px rgba(0,0,0,0.1)",
  };
  return { variables: variables as unknown as McpUiStyles, css: { fonts: "" } };
}
