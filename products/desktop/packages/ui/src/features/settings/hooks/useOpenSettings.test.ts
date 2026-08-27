import { beforeEach, describe, expect, it, vi } from "vitest";

const navigateToSettings = vi.fn();
const isOnSettingsRoute = vi.fn(() => false);

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToSettings: (...args: unknown[]) => navigateToSettings(...args),
  isOnSettingsRoute: () => isOnSettingsRoute(),
  canGoBackInHistory: vi.fn(),
  goBackInHistory: vi.fn(),
  navigateToNewTask: vi.fn(),
}));

import { openSettings } from "./useOpenSettings";

describe("openSettings", () => {
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

  // "Back to app" is a single history step, so a category change from inside
  // settings must replace — otherwise it lands on the previous category.
  it("replaces the entry when already inside settings", () => {
    isOnSettingsRoute.mockReturnValue(true);
    openSettings("shortcuts");
    expect(navigateToSettings).toHaveBeenCalledWith("shortcuts", {
      replace: true,
    });
  });
});
