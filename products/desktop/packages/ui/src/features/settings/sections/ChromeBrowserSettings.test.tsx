import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChromeBrowserSettings } from "./ChromeBrowserSettings";

const mocks = vi.hoisted(() => ({
  reconnect: vi.fn(),
  disconnect: vi.fn(),
  status: "connected",
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    agent: {
      browserStatus: {
        queryOptions: () => ({
          queryKey: ["browser-status"],
          queryFn: async () => ({ status: mocks.status }),
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

describe("ChromeBrowserSettings", () => {
  let queryClient: QueryClient;

  beforeEach(async () => {
    vi.resetAllMocks();
    mocks.status = "connected";
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <ChromeBrowserSettings />
      </QueryClientProvider>,
    );
    await screen.findByRole("button", { name: "Disconnect Chrome" });
  });

  afterEach(() => {
    cleanup();
    queryClient.clear();
  });

  it.each([
    ["idle", "Connect Chrome"],
    ["disconnected", "Connect Chrome"],
    ["error", "Connect Chrome"],
    ["connected", "Disconnect Chrome"],
    ["connecting", "Cancel connection"],
  ])("shows only the available action for %s", async (status, label) => {
    mocks.status = status;
    act(() => queryClient.setQueryData(["browser-status"], { status }));
    await screen.findByRole("button", { name: label });
    const actions = screen.getAllByRole("button", {
      name: /^(Connect Chrome|Disconnect Chrome|Cancel connection)$/,
    });
    expect(actions).toHaveLength(1);
    expect(actions[0]).toHaveTextContent(label);
    expect(screen.queryByText("Disconnected")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Connected", { exact: true }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Ready to connect")).not.toBeInTheDocument();
  });

  it("offers cancel while a connection is pending", async () => {
    mocks.status = "disconnected";
    act(() =>
      queryClient.setQueryData(["browser-status"], { status: "disconnected" }),
    );
    let finish!: () => void;
    mocks.reconnect.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Connect Chrome" }),
    );
    expect(
      screen.queryByRole("button", { name: "Connect Chrome" }),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel connection" }));
    expect(mocks.reconnect).toHaveBeenCalledOnce();
    expect(mocks.disconnect).toHaveBeenCalledOnce();
    finish();
    await screen.findByRole("button", { name: "Connect Chrome" });
  });

  it("shows disconnect after Chrome connects", async () => {
    mocks.status = "disconnected";
    act(() =>
      queryClient.setQueryData(["browser-status"], { status: mocks.status }),
    );
    mocks.reconnect.mockImplementation(async () => {
      mocks.status = "connected";
    });
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Connect Chrome" }),
    );
    expect(
      await screen.findByRole("button", { name: "Disconnect Chrome" }),
    ).toBeInTheDocument();
  });

  it("prevents duplicate disconnect requests", async () => {
    let finish!: () => void;
    mocks.disconnect.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const user = userEvent.setup();
    const button = screen.getByRole("button", { name: "Disconnect Chrome" });
    await user.click(button);
    expect(button).toHaveAttribute("aria-disabled", "true");
    await user.click(button);
    expect(mocks.disconnect).toHaveBeenCalledOnce();
    finish();
    await waitFor(() =>
      expect(button).not.toHaveAttribute("aria-disabled", "true"),
    );
  });

  it("keeps the disconnect action if disconnect fails", async () => {
    mocks.disconnect.mockRejectedValue(new Error("Disconnect failed"));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Disconnect Chrome" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't disconnect from Chrome",
    );
    expect(
      screen.getByRole("button", { name: "Disconnect Chrome" }),
    ).toBeInTheDocument();
  });
});
