import { DARK_APP_BACKGROUND_COLOR } from "@posthog/shared/constants";

interface PlatformWindowConfig {
  acceptFirstMouse?: boolean;
  titleBarOverlay?:
    | boolean
    | { color: string; symbolColor: string; height: number };
  titleBarStyle?: "hidden";
  trafficLightPosition?: { x: number; y: number };
}

export function getPlatformWindowConfig(
  platform: NodeJS.Platform,
): PlatformWindowConfig {
  if (platform === "darwin") {
    return {
      // Let a control handle the click that also reactivates the app.
      acceptFirstMouse: true,
      // "hidden", not "hiddenInset": hiddenInset keeps macOS's own inset and
      // ignores trafficLightPosition's y.
      titleBarStyle: "hidden",
      // Centre the traffic lights vertically with the title bar controls.
      trafficLightPosition: { x: 14, y: 12 },
      // Expose titlebar-area-* so the renderer clears the OS-sized controls.
      titleBarOverlay: true,
    };
  }

  if (platform === "win32") {
    return {
      titleBarStyle: "hidden",
      titleBarOverlay: {
        color: DARK_APP_BACKGROUND_COLOR,
        symbolColor: "#ffffff",
        height: 36,
      },
    };
  }

  return {};
}
