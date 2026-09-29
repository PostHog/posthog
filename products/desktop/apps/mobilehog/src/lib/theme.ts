import { colors as brand } from "@posthog/brand/colors";
import { DynamicColorIOS } from "react-native";

// Every token resolves per trait collection, so static stylesheets follow the
// scheme without re-rendering. Light is posthog.com's tan and ink; dark inverts.
const dyn = (light: string, dark: string) => DynamicColorIOS({ light, dark });

export const colors = {
  bg: dyn("#EEEFE9", "#151515"),
  bgDeep: dyn("#E4E6DE", "#0C0C0C"),
  // Raised surfaces: a half step between the page and white.
  bgRaised: dyn("#F7F7F3", "#1C1C1C"),
  surface: dyn("#FFFFFF", "#222222"),
  ink: dyn("#151515", "#EEEFE9"),
  inkSoft: dyn("#4F5150", "#B8BAB4"),
  inkMute: dyn("#8F918D", "#7C7E7A"),
  line: dyn("rgba(21, 21, 21, 0.08)", "rgba(238, 239, 233, 0.10)"),
  fill: dyn("rgba(21, 21, 21, 0.06)", "rgba(238, 239, 233, 0.08)"),
  code: dyn("rgba(21, 21, 21, 0.05)", "rgba(238, 239, 233, 0.07)"),
  glass: dyn("rgba(255, 255, 255, 0.55)", "rgba(40, 40, 40, 0.55)"),
  glassTint: dyn("rgba(255, 255, 255, 0.75)", "rgba(34, 34, 34, 0.75)"),
  sceneTint: dyn("rgba(238, 239, 233, 0.72)", "rgba(21, 21, 21, 0.72)"),
  accent: brand.tangerine.core,
  danger: brand.coral.core,
  ok: brand.green.core,
  // High-contrast buttons: ink on tan, tan on ink.
  dark: dyn("#151515", "#EEEFE9"),
  darkText: dyn("#EEEFE9", "#151515"),
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
