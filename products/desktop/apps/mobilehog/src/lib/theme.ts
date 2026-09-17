import { Platform } from "react-native";

export const colors = {
  bg: "#F4F3EE",
  bgDeep: "#ECEAE3",
  ink: "#1C1B18",
  inkSoft: "#5B5952",
  inkMute: "#9A978E",
  line: "rgba(28, 27, 24, 0.08)",
  glass: "rgba(255, 255, 255, 0.55)",
  accent: "#D9755B",
  danger: "#C24A3A",
  ok: "#4F8A5B",
  dark: "#1C1B18",
  darkText: "#F4F3EE",
  code: "rgba(28, 27, 24, 0.05)",
};

export const fonts = {
  serif: Platform.select({ ios: "Georgia", default: "serif" }),
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
