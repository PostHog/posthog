/**
 * Maps Twig's Radix UI theme to the MCP Apps host styling spec.
 *
 * MCP Apps receive a set of CSS variables from the host so they can render with
 * a consistent look and feel. This module reads Twig's computed CSS custom
 * properties (gray scale, accent colors, font sizes, radii, etc.) and maps them
 * to the spec-defined variable names (e.g. --color-background-primary,
 * --font-text-sm-size, --border-radius-xs).
 *
 * The variables are sent to the app during `ui/initialize` and updated via
 * `ui/notifications/host-context-changed` on theme changes.
 *
 * @see https://modelcontextprotocol.io/specification/2025-03-26/extensions/mcp-apps
 */

interface HostStyles {
  variables: Record<string, string>;
  css: { fonts: string };
}

function getVar(name: string): string {
  return getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
}

export function buildHostStyles(_isDarkMode: boolean): HostStyles {
  const variables: Record<string, string> = {
    // --- Background colors ---
    "--color-background-primary": getVar("--gray-1"),
    "--color-background-secondary": getVar("--gray-2"),
    "--color-background-tertiary": getVar("--gray-3"),
    "--color-background-inverse": getVar("--gray-12"),
    "--color-background-ghost": "transparent",
    "--color-background-info": getVar("--accent-3"),
    "--color-background-danger": getVar("--red-3"),
    "--color-background-success": getVar("--green-3"),
    "--color-background-warning": getVar("--yellow-3"),
    "--color-background-disabled": getVar("--gray-3"),

    // --- Text colors ---
    "--color-text-primary": getVar("--gray-12"),
    "--color-text-secondary": getVar("--gray-11"),
    "--color-text-tertiary": getVar("--gray-10"),
    "--color-text-inverse": getVar("--gray-1"),
    "--color-text-ghost": getVar("--gray-10"),
    "--color-text-info": getVar("--accent-11"),
    "--color-text-danger": getVar("--red-11"),
    "--color-text-success": getVar("--green-11"),
    "--color-text-warning": getVar("--yellow-11"),
    "--color-text-disabled": getVar("--gray-6"),

    // --- Border colors ---
    "--color-border-primary": getVar("--gray-6"),
    "--color-border-secondary": getVar("--gray-5"),
    "--color-border-tertiary": getVar("--gray-3"),
    "--color-border-inverse": getVar("--gray-12"),
    "--color-border-ghost": "transparent",
    "--color-border-info": getVar("--accent-6"),
    "--color-border-danger": getVar("--red-6"),
    "--color-border-success": getVar("--green-6"),
    "--color-border-warning": getVar("--yellow-6"),
    "--color-border-disabled": getVar("--gray-5"),

    // --- Ring / focus colors ---
    "--color-ring-primary": getVar("--accent-9"),
    "--color-ring-secondary": getVar("--gray-6"),
    "--color-ring-inverse": getVar("--gray-1"),
    "--color-ring-info": getVar("--accent-9"),
    "--color-ring-danger": getVar("--red-9"),
    "--color-ring-success": getVar("--green-9"),
    "--color-ring-warning": getVar("--yellow-9"),

    // --- Fonts ---
    "--font-sans":
      getVar("--default-font-family") ||
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
    "--font-mono":
      getVar("--code-font-family") ||
      "'Berkeley Mono', 'JetBrains Mono', monospace",

    // --- Font weights ---
    "--font-weight-normal": "400",
    "--font-weight-medium": "500",
    "--font-weight-semibold": "600",
    "--font-weight-bold": "700",

    // --- Font sizes (spec names) ---
    "--font-text-xs-size": getVar("--font-size-1") || "12px",
    "--font-text-sm-size": getVar("--font-size-2") || "14px",
    "--font-text-md-size": getVar("--font-size-3") || "16px",
    "--font-text-lg-size": getVar("--font-size-4") || "18px",
    "--font-heading-xs-size": getVar("--font-size-4") || "18px",
    "--font-heading-sm-size": getVar("--font-size-5") || "20px",
    "--font-heading-md-size": getVar("--font-size-6") || "24px",
    "--font-heading-lg-size": getVar("--font-size-7") || "28px",
    "--font-heading-xl-size": getVar("--font-size-8") || "35px",
    "--font-heading-2xl-size": getVar("--font-size-9") || "60px",
    "--font-heading-3xl-size": "72px",

    // --- Line heights ---
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

    // --- Border radius ---
    "--border-radius-xs": "2px",
    "--border-radius-sm": getVar("--radius-2") || "4px",
    "--border-radius-md": getVar("--radius-3") || "8px",
    "--border-radius-lg": getVar("--radius-4") || "12px",
    "--border-radius-xl": getVar("--radius-5") || "16px",
    "--border-radius-full": "9999px",

    // --- Border width ---
    "--border-width-regular": "1px",

    // --- Shadows ---
    "--shadow-hairline": `0 0 0 1px ${getVar("--gray-6") || "rgba(0,0,0,0.1)"}`,
    "--shadow-sm": "0 1px 2px rgba(0,0,0,0.05)",
    "--shadow-md":
      "0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06)",
    "--shadow-lg":
      "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05)",
  };

  // Build font CSS (include @font-face if Berkeley Mono is available)
  const fontCss = buildFontCss();

  return {
    variables,
    css: { fonts: fontCss },
  };
}

function buildFontCss(): string {
  // Check if Berkeley Mono is loaded
  const berkeleyMonoAvailable = document.fonts.check("12px 'Berkeley Mono'");

  if (!berkeleyMonoAvailable) {
    return "";
  }

  // Berkeley Mono is available on the host, but the sandboxed iframe
  // can't access host fonts. We provide the font-family declarations
  // so the app knows the preferred font, but the actual font rendering
  // falls back to JetBrains Mono or system monospace in the iframe.
  return "";
}

export function buildHostStylesCss(variables: Record<string, string>): string {
  return Object.entries(variables)
    .map(([key, value]) => `${key}: ${value};`)
    .join("\n");
}
