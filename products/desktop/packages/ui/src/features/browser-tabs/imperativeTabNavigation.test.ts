import type { TabsSnapshot } from "@posthog/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getCurrentBrowserTabId,
  navigateBrowserTab,
} from "./imperativeTabNavigation";

const mocks = vi.hoisted(() => ({
  getRouterOrNull: vi.fn(),
  applyLocalTransform: vi.fn(),
  persistTabTarget: vi.fn(),
  readMirror: vi.fn(),
  setTabTarget: vi.fn(),
}));

vi.mock("@posthog/ui/router/routerRef", () => ({
  getRouterOrNull: mocks.getRouterOrNull,
}));
vi.mock("./tabsSync", () => ({
  applyLocalTransform: mocks.applyLocalTransform,
  persistTabTarget: mocks.persistTabTarget,
  readMirror: mocks.readMirror,
}));
vi.mock("@posthog/shared", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@posthog/shared")>();
  return { ...actual, setTabTarget: mocks.setTabTarget };
});

const destination = {
  href: "/tasks/task-1",
  title: "Created task",
  dashboardId: null,
  taskId: "task-1",
  channelId: null,
  channelSection: null,
  appView: null,
};

function snapshot(): TabsSnapshot {
  return {
    windows: [
      {
        id: "window-1",
        isPrimary: true,
        bounds: null,
        activeTabId: "tab-b",
      },
    ],
    tabs: [
      {
        id: "tab-a",
        windowId: "window-1",
        href: "/new",
        viewState: { title: "New task" },
        dashboardId: null,
        taskId: null,
        channelId: null,
        channelSection: null,
        appView: null,
        position: 1000,
        scrollState: null,
        createdAt: 1,
        lastActiveAt: 1,
      },
      {
        id: "tab-b",
        windowId: "window-1",
        href: "/inbox",
        viewState: { title: "Inbox" },
        dashboardId: null,
        taskId: null,
        channelId: null,
        channelSection: null,
        appView: "inbox",
        position: 2000,
        scrollState: null,
        createdAt: 2,
        lastActiveAt: 2,
      },
    ],
  };
}

describe("imperative browser-tab navigation", () => {
  const history = { location: { state: { tabId: "tab-b" } } };

  beforeEach(() => {
    vi.clearAllMocks();
    history.location.state.tabId = "tab-b";
    mocks.getRouterOrNull.mockReturnValue({ history });
    mocks.readMirror.mockReturnValue(snapshot());
    mocks.applyLocalTransform.mockImplementation((transform) =>
      transform(snapshot()),
    );
    mocks.setTabTarget.mockImplementation((state) => state);
  });

  it("reads the tab attached to the current history entry", () => {
    expect(getCurrentBrowserTabId()).toBe("tab-b");
  });

  it("uses ordinary navigation when the originating tab is still active", () => {
    history.location.state.tabId = "tab-a";
    const fallback = vi.fn();

    expect(navigateBrowserTab("tab-a", destination, fallback)).toBe("active");
    expect(fallback).toHaveBeenCalledOnce();
    expect(mocks.applyLocalTransform).not.toHaveBeenCalled();
  });

  it("retargets an inactive origin without activating it", () => {
    const fallback = vi.fn();

    expect(navigateBrowserTab("tab-a", destination, fallback)).toBe(
      "background",
    );
    expect(mocks.setTabTarget).toHaveBeenCalledWith(
      expect.any(Object),
      expect.objectContaining({
        tabId: "tab-a",
        href: destination.href,
        taskId: "task-1",
        activate: false,
      }),
    );
    expect(mocks.persistTabTarget).toHaveBeenCalledWith(
      expect.objectContaining({ tabId: "tab-a", activate: false }),
    );
    expect(fallback).not.toHaveBeenCalled();
  });

  it("uses ordinary navigation when browser tabs are unavailable", () => {
    const fallback = vi.fn();

    expect(navigateBrowserTab(null, destination, fallback)).toBe("active");
    expect(fallback).toHaveBeenCalledOnce();
  });
});
