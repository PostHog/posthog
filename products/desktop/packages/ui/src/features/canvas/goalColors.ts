import type { GoalStatus } from "@posthog/core/canvas/contextDocument";
import { useThemeStore } from "@posthog/ui/shell/themeStore";

export interface GoalPalette {
  green: string;
  red: string;
  muted: string;
}

const PALETTE: Record<"light" | "dark", GoalPalette> = {
  light: { green: "#1f9d55", red: "#dc4a3d", muted: "#9a9a92" },
  dark: { green: "#5fd38d", red: "#ff7b6e", muted: "#7d7d76" },
};

export function useGoalPalette(): GoalPalette {
  const isDarkMode = useThemeStore((state) => state.isDarkMode);
  return isDarkMode ? PALETTE.dark : PALETTE.light;
}

export function statusColor(status: GoalStatus, palette: GoalPalette): string {
  if (status === "met" || status === "on_track") return palette.green;
  if (status === "behind") return palette.red;
  return palette.muted;
}
