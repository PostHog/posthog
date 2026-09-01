import type { McpUiStyles } from "@modelcontextprotocol/ext-apps/app-bridge";
import type { ThemeColors } from "@/lib/theme";

/**
 * Builds the `McpUiStyles` payload an MCP App receives at initialize / on
 * host-context-changed. Mirrors the desktop builder (apps/code/src/renderer/
 * features/mcp-apps/utils/mcp-app-theme.ts) but reads from our mobile
 * `ThemeColors` instead of computed CSS variables (which don't exist in RN).
 *
 * MCP Apps render inside a sandboxed WebView, so we hand them a minimal but
 * complete set of design tokens — they have no other access to our theme.
 */
export function buildMcpHostStyles(
  themeColors: ThemeColors,
  isDarkMode: boolean,
): { variables: McpUiStyles; css: { fonts: string } } {
  const variables: Record<string, string> = {
    "--color-background-primary": themeColors.background,
    "--color-background-secondary": themeColors.gray[2],
    "--color-background-tertiary": themeColors.gray[3],
    "--color-background-inverse": themeColors.gray[12],
    "--color-background-ghost": "transparent",
    "--color-background-info": themeColors.accent[3],
    "--color-background-danger": isDarkMode ? "#3b0d0d" : "#fde8e8",
    "--color-background-success": isDarkMode ? "#0f2d18" : "#dcfce7",
    "--color-background-warning": isDarkMode ? "#3a2c00" : "#fef3c7",
    "--color-background-disabled": themeColors.gray[3],

    "--color-text-primary": themeColors.gray[12],
    "--color-text-secondary": themeColors.gray[11],
    "--color-text-tertiary": themeColors.gray[10],
    "--color-text-inverse": themeColors.gray[1],
    "--color-text-ghost": themeColors.gray[10],
    "--color-text-info": themeColors.accent[11],
    "--color-text-danger": themeColors.status.error,
    "--color-text-success": themeColors.status.success,
    "--color-text-warning": themeColors.status.warning,
    "--color-text-disabled": themeColors.gray[6],

    "--color-border-primary": themeColors.gray[6],
    "--color-border-secondary": themeColors.gray[5],
    "--color-border-tertiary": themeColors.gray[3],
    "--color-border-inverse": themeColors.gray[12],
    "--color-border-ghost": "transparent",
    "--color-border-info": themeColors.accent[6],
    "--color-border-danger": themeColors.status.error,
    "--color-border-success": themeColors.status.success,
    "--color-border-warning": themeColors.status.warning,
    "--color-border-disabled": themeColors.gray[5],

    "--color-ring-primary": themeColors.accent[9],
    "--color-ring-secondary": themeColors.gray[6],
    "--color-ring-inverse": themeColors.gray[1],
    "--color-ring-info": themeColors.accent[9],
    "--color-ring-danger": themeColors.status.error,
    "--color-ring-success": themeColors.status.success,
    "--color-ring-warning": themeColors.status.warning,

    "--font-sans":
      "-apple-system, BlinkMacSystemFont, 'Open Runde', 'Segoe UI', Roboto, sans-serif",
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

    "--border-radius-xs": "2px",
    "--border-radius-sm": "4px",
    "--border-radius-md": "8px",
    "--border-radius-lg": "12px",
    "--border-radius-xl": "16px",
    "--border-radius-full": "9999px",

    "--border-width-regular": "1px",

    "--shadow-hairline": `0 0 0 1px ${themeColors.gray[6]}`,
    "--shadow-sm": "0 1px 2px rgba(0,0,0,0.05)",
    "--shadow-md":
      "0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06)",
    "--shadow-lg":
      "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05)",
  };

  return {
    variables: variables as unknown as McpUiStyles,
    css: { fonts: "" },
  };
}
