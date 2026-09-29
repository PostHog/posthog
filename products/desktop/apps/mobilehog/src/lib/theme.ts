import { colors as brand } from "@posthog/brand/colors";

export const colors = {
  // posthog.com's tan and ink; the brand package only ships the chromatic set.
  bg: "#EEEFE9",
  bgDeep: "#E4E6DE",
  ink: "#151515",
  inkSoft: "#4F5150",
  inkMute: "#8F918D",
  line: "rgba(21, 21, 21, 0.08)",
  glass: "rgba(255, 255, 255, 0.55)",
  accent: brand.tangerine.core,
  danger: brand.coral.core,
  ok: brand.green.core,
  dark: "#151515",
  darkText: "#EEEFE9",
  code: "rgba(21, 21, 21, 0.05)",
};

// RoundHog is the brand face; each weight is its own registered family.
export const fonts = {
  sans: "RoundHog",
  sansMedium: "RoundHog-Medium",
  sansSemi: "RoundHog-SemiBold",
  sansBold: "RoundHog-Bold",
  sansItalic: "RoundHog-Italic",
  serif: "RoundHog-SemiBold",
  mono: "JetBrainsMono-Regular",
  monoMedium: "JetBrainsMono-Medium",
};

// Shared by the drawer layout and the shadow ghost behind the chat layer.
export const drawer = {
  widthFraction: 0.82,
  sceneRadius: 44,
};

export const radius = {
  pill: 999,
  card: 24,
  bubble: 18,
};
