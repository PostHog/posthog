import { beforeEach, describe, expect, it, vi } from "vitest";

const navigateToSettings = vi.fn();
const leaveSettingsRoute = vi.fn();
const isOnSettingsRoute = vi.fn(() => false);

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToSettings: (...args: unknown[]) => navigateToSettings(...args),
  isOnSettingsRoute: () => isOnSettingsRoute(),
  isSettingsRouteId: (routeId: string) => routeId.includes("/settings/"),
  leaveSettingsRoute: () => leaveSettingsRoute(),
}));

import { closeSettings, openSettings } from "./useOpenSettings";

describe("settings navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    isOnSettingsRoute.mockReturnValue(false);
  });

  it("stacks an entry when entering settings from the app", () => {
    openSettings("github");
    expect(navigateToSettings).toHaveBeenCalledWith("github", {
      replace: false,
    });
  });

  it("replaces the entry when already inside settings", () => {
    isOnSettingsRoute.mockReturnValue(true);
    openSettings("shortcuts");
    expect(navigateToSettings).toHaveBeenCalledWith("shortcuts", {
      replace: true,
    });
  });

  it.each([true, false])(
    "leaves settings by route when on a settings route: %s",
    (onRoute) => {
      isOnSettingsRoute.mockReturnValue(onRoute);
      closeSettings();
      expect(leaveSettingsRoute).toHaveBeenCalledTimes(onRoute ? 1 : 0);
    },
  );
});
