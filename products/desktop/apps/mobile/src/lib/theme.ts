import { useColorScheme, vars } from "nativewind";

/**
 * Single source of truth for all theme colors.
 * Defined as hex for readability, converted to RGB for NativeWind vars().
 */
// Color palette mirrored from the desktop app (apps/code globals.css).
// Light: slate gray + orange accent. Dark: slate gray + yellow accent.
const colors = {
  light: {
    gray: {
      1: "#f2f3ee",
      2: "#eceee8",
      3: "#e4e5de",
      4: "#d8dbd1",
      5: "#cbd0c3",
      6: "#bcc1b4",
      7: "#a9af9f",
      8: "#93998a",
      9: "#6b7165",
      10: "#5a6054",
      11: "#3a4036",
      12: "#0d0d0d",
    },
    accent: {
      1: "#fff5f0",
      2: "#ffe8dc",
      3: "#ffd0b8",
      4: "#ffb38a",
      5: "#ff8f56",
      6: "#f57030",
      7: "#e05a18",
      8: "#c94800",
      9: "#f54d00",
      10: "#e64600",
      11: "#a33300",
      12: "#4d1800",
      contrast: "#ffffff",
    },
    status: {
      success: "#16a34a",
      error: "#dc2626",
      warning: "#d97706",
      info: "#2563eb",
    },
    background: "#f2f3ee",
    // "Card" surface — used for raised UI like buttons, composer card, pills.
    // Pure white in light mode for max contrast against the cream background;
    // gray-3 in dark mode so cards lift slightly off the bg.
    card: "#ffffff",
  },
  dark: {
    gray: {
      1: "#131316",
      2: "#18181f",
      3: "#1e1e28",
      4: "#24243e",
      5: "#2a2a37",
      6: "#2e2e3d",
      7: "#40405a",
      8: "#616180",
      9: "#7c7c9e",
      10: "#8d8daa",
      11: "#9898b6",
      12: "#e6e6e6",
    },
    accent: {
      1: "#14120a",
      2: "#1a1608",
      3: "#261e07",
      4: "#362900",
      5: "#443300",
      6: "#524007",
      7: "#6b561a",
      8: "#8c7230",
      9: "#f8be2a",
      10: "#ebb520",
      11: "#fcc84e",
      12: "#fde8b8",
      contrast: "#1a1200",
    },
    status: {
      success: "#4ade80",
      error: "#f87171",
      warning: "#fbbf24",
      info: "#60a5fa",
    },
    background: "#131316",
    card: "#1e1e28",
  },
} as const;

// Convert hex to RGB space-separated format for NativeWind vars()
function hexToRgb(hex: string): string {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result) return "0 0 0";
  return `${parseInt(result[1], 16)} ${parseInt(result[2], 16)} ${parseInt(result[3], 16)}`;
}

// Convert hex to rgba format with alpha
function hexToRgba(hex: string, alpha: number): string {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!result) return `rgba(0,0,0,${alpha})`;
  const r = parseInt(result[1], 16);
  const g = parseInt(result[2], 16);
  const b = parseInt(result[3], 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// Generate NativeWind vars() from color definitions
function createThemeVars(theme: (typeof colors)["light" | "dark"]) {
  return vars({
    "--gray-1": hexToRgb(theme.gray[1]),
    "--gray-2": hexToRgb(theme.gray[2]),
    "--gray-3": hexToRgb(theme.gray[3]),
    "--gray-4": hexToRgb(theme.gray[4]),
    "--gray-5": hexToRgb(theme.gray[5]),
    "--gray-6": hexToRgb(theme.gray[6]),
    "--gray-7": hexToRgb(theme.gray[7]),
    "--gray-8": hexToRgb(theme.gray[8]),
    "--gray-9": hexToRgb(theme.gray[9]),
    "--gray-10": hexToRgb(theme.gray[10]),
    "--gray-11": hexToRgb(theme.gray[11]),
    "--gray-12": hexToRgb(theme.gray[12]),
    "--accent-1": hexToRgb(theme.accent[1]),
    "--accent-2": hexToRgb(theme.accent[2]),
    "--accent-3": hexToRgb(theme.accent[3]),
    "--accent-4": hexToRgb(theme.accent[4]),
    "--accent-5": hexToRgb(theme.accent[5]),
    "--accent-6": hexToRgb(theme.accent[6]),
    "--accent-7": hexToRgb(theme.accent[7]),
    "--accent-8": hexToRgb(theme.accent[8]),
    "--accent-9": hexToRgb(theme.accent[9]),
    "--accent-10": hexToRgb(theme.accent[10]),
    "--accent-11": hexToRgb(theme.accent[11]),
    "--accent-12": hexToRgb(theme.accent[12]),
    "--accent-contrast": hexToRgb(theme.accent.contrast),
    "--status-success": hexToRgb(theme.status.success),
    "--status-error": hexToRgb(theme.status.error),
    "--status-warning": hexToRgb(theme.status.warning),
    "--status-info": hexToRgb(theme.status.info),
    "--background": hexToRgb(theme.background),
    "--card": hexToRgb(theme.card),
  });
}

// NativeWind vars() for runtime theming (used in root View style)
export const lightTheme = createThemeVars(colors.light);
export const darkTheme = createThemeVars(colors.dark);

// Types
export type ThemeColors = (typeof colors)["light" | "dark"];

/**
 * Hook to get raw hex color values for native components.
 * Use for: ActivityIndicator, headerStyle, headerTintColor, RefreshControl, etc.
 *
 * For styled components, use Tailwind classes:
 * - bg-gray-1, text-gray-12, border-gray-6
 * - bg-accent-9, text-accent-11
 * - bg-background
 */
export function useThemeColors(): ThemeColors {
  const { colorScheme } = useColorScheme();
  return colorScheme === "dark" ? colors.dark : colors.light;
}

/**
 * Convert hex color to rgba format.
 * Useful for creating transparent variants of theme colors (e.g., for gradients).
 */
export function toRgba(hex: string, alpha: number): string {
  return hexToRgba(hex, alpha);
}
