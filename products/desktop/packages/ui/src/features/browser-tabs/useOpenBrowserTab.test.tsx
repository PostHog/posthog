import { browserTabsStore } from "@posthog/core/browser-tabs/browserTabsStore";
import { createMemoryHistory } from "@tanstack/react-router";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  client: { openTab: vi.fn() },
  logger: { error: vi.fn() },
  history: null as ReturnType<typeof createMemoryHistory> | null,
}));

vi.mock("@posthog/di/react", () => ({
  useService: (token: symbol) =>
    String(token).includes("BrowserTabsClient") ? mocks.client : mocks.logger,
}));
vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    useRouter: () => ({ history: mocks.history }),
  };
});

import { useOpenBrowserTab } from "./useOpenBrowserTab";

describe("useOpenBrowserTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.history = createMemoryHistory({ initialEntries: ["/activity"] });
    browserTabsStore.getState().setSnapshot({
      windows: [
        { id: "window-1", isPrimary: true, bounds: null, activeTabId: "tab-1" },
      ],
      tabs: [
        {
          id: "tab-1",
          windowId: "window-1",
          href: "/activity",
          viewState: null,
          dashboardId: null,
          taskId: null,
          channelId: null,
          channelSection: null,
          appView: "activity",
          position: 1000,
          scrollState: null,
          createdAt: 1,
          lastActiveAt: 1,
        },
      ],
    });
    mocks.client.openTab.mockImplementation(
      async () => browserTabsStore.getState().snapshot,
    );
  });

  it("opens and focuses independent tabs without changing the source tab", async () => {
    const { result } = renderHook(() => useOpenBrowserTab());

    act(() => {
      result.current("/inbox");
      result.current("/inbox");
    });

    const snapshot = browserTabsStore.getState().snapshot;
    const inboxTabs = snapshot.tabs.filter((tab) => tab.href === "/inbox");
    expect(snapshot.tabs.find((tab) => tab.id === "tab-1")?.href).toBe(
      "/activity",
    );
    expect(inboxTabs).toHaveLength(2);
    expect(inboxTabs[0].id).not.toBe(inboxTabs[1].id);
    expect(snapshot.windows[0].activeTabId).toBe(inboxTabs[1].id);
    expect(mocks.history?.location).toMatchObject({
      href: "/inbox",
      state: { tabId: inboxTabs[1].id },
    });
    await waitFor(() => expect(mocks.client.openTab).toHaveBeenCalledTimes(2));
  });
});
