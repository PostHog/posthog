import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChromeBrowserSettings } from "./ChromeBrowserSettings";

const mocks = vi.hoisted(() => ({
  reconnect: vi.fn(),
  disconnect: vi.fn(),
  setEnabled: vi.fn(),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    agent: {
      browserStatus: {
        queryOptions: () => ({
          queryKey: ["browser-status"],
          queryFn: async () => ({ status: "connected" }),
        }),
      },
      reconnectBrowser: {
        mutationOptions: () => ({ mutationFn: mocks.reconnect }),
      },
      disconnectBrowser: {
        mutationOptions: () => ({ mutationFn: mocks.disconnect }),
      },
    },
    os: {
      openChromeRemoteDebugging: {
        mutationOptions: () => ({ mutationFn: vi.fn() }),
      },
    },
  }),
}));

vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: (
    selector: (state: {
      browserIntegrationEnabled: boolean;
      setBrowserIntegrationEnabled: (enabled: boolean) => void;
    }) => unknown,
  ) =>
    selector({
      browserIntegrationEnabled: true,
      setBrowserIntegrationEnabled: mocks.setEnabled,
    }),
}));

describe("ChromeBrowserSettings", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.resetAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ChromeBrowserSettings />
      </QueryClientProvider>,
    );
  });

  afterEach(() => {
    cleanup();
    queryClient.clear();
  });

  it.each([
    ["Reconnect Chrome", "reconnect"],
    ["Disconnect Chrome", "disconnect"],
  ] as const)("prevents duplicate %s requests", async (label, action) => {
    let finish!: () => void;
    mocks[action].mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const user = userEvent.setup();
    const button = screen.getByRole("button", { name: label });
    await user.click(button);
    expect(button).toHaveAttribute("aria-disabled", "true");
    await user.click(button);
    expect(mocks[action]).toHaveBeenCalledOnce();
    finish();
    await waitFor(() =>
      expect(button).not.toHaveAttribute("aria-disabled", "true"),
    );
  });

  it("keeps access enabled if disconnect fails", async () => {
    mocks.disconnect.mockRejectedValue(new Error("Disconnect failed"));
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("switch", {
        name: "Enable Google Chrome browser access",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't change the Chrome connection",
    );
    expect(mocks.setEnabled).not.toHaveBeenCalled();
  });
});
