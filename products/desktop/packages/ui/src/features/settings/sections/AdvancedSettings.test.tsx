import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const openChromeRemoteDebugging = vi.fn();
let chromeSetupError = false;

vi.mock("@posthog/di/react", () => ({
  useServiceOptional: () => undefined,
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    agent: {
      rtkStatus: { queryOptions: () => ({}) },
      browserStatus: { queryOptions: () => ({}) },
      reconnectBrowser: { mutationOptions: () => ({}) },
      disconnectBrowser: { mutationOptions: () => ({}) },
    },
    os: {
      openChromeRemoteDebugging: { mutationOptions: () => ({}) },
    },
  }),
}));

vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
}));

vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: (
    selector: (state: {
      autoPublishCloudRuns: boolean;
      debugLogsCloudRuns: boolean;
      rtkEnabledCloud: boolean;
      rtkEnabledLocal: boolean;
      setAutoPublishCloudRuns: () => void;
      setDebugLogsCloudRuns: () => void;
      setRtkEnabledCloud: () => void;
      setRtkEnabledLocal: () => void;
    }) => unknown,
  ) =>
    selector({
      autoPublishCloudRuns: false,
      debugLogsCloudRuns: false,
      rtkEnabledCloud: false,
      rtkEnabledLocal: false,
      setAutoPublishCloudRuns: vi.fn(),
      setDebugLogsCloudRuns: vi.fn(),
      setRtkEnabledCloud: vi.fn(),
      setRtkEnabledLocal: vi.fn(),
    }),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: undefined }),
  useMutation: () => ({
    isError: chromeSetupError,
    isPending: false,
    mutate: openChromeRemoteDebugging,
  }),
}));

import { AdvancedSettings } from "./AdvancedSettings";

describe("AdvancedSettings", () => {
  it("opens Chrome remote debugging setup", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <AdvancedSettings />
      </Theme>,
    );

    await user.click(screen.getByText("Connection help"));
    await user.click(
      screen.getByRole("button", {
        name: "Open Chrome remote debugging settings",
      }),
    );

    expect(openChromeRemoteDebugging).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole("switch", {
        name: "Enable Google Chrome browser access",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "First, enable remote debugging in Chrome. Then select Connect Chrome and approve the request in Chrome.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a Chrome setup error", () => {
    chromeSetupError = true;
    render(
      <Theme>
        <AdvancedSettings />
      </Theme>,
    );

    expect(
      screen.getByText(
        "Couldn't open Chrome settings. Check that Google Chrome is installed.",
      ),
    ).toBeInTheDocument();

    chromeSetupError = false;
  });
});
