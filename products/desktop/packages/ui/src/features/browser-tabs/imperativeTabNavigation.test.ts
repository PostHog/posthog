import type { TabsSnapshot } from "@posthog/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { BrowserTabsClient } from "./browserTabsClient";
import {
  focusExistingTab,
  getCurrentBrowserTabId,
  navigateBrowserTab,
  openInNewBrowserTab,
} from "./imperativeTabNavigation";

const mocks = vi.hoisted(() => ({
  getRouterOrNull: vi.fn(),
  applyLocalTransform: vi.fn(),
  persistTabTarget: vi.fn(),
  readMirror: vi.fn(),
  setTabTarget: vi.fn(),
  persistWrite: vi.fn(),
  reseedMirror: vi.fn(),
}));

vi.mock("@posthog/ui/router/routerRef", () => ({
  getRouterOrNull: mocks.getRouterOrNull,
}));
vi.mock("./tabsSync", () => ({
  applyLocalTransform: mocks.applyLocalTransform,
  persistTabTarget: mocks.persistTabTarget,
  readMirror: mocks.readMirror,
  persistWrite: mocks.persistWrite,
  reseedMirror: mocks.reseedMirror,
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

/** Only openTab is on the open path; the rest of the client stays unmocked. */
const client = (): BrowserTabsClient =>
  ({ openTab: vi.fn() }) as unknown as BrowserTabsClient;

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
  const history = {
    location: { state: { tabId: "tab-b" as string | undefined } },
    push: vi.fn(),
  };

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

  it("opens an inbound destination in its own tab without touching the current one", async () => {
    const tabId = await openInNewBrowserTab(client(), destination);

    expect(tabId).toEqual(expect.any(String));
    const mirror = mocks.applyLocalTransform.mock.results[0]
      ?.value as TabsSnapshot;
    // Appends to the window without rewriting either existing tab's location.
    expect(mirror.tabs).toHaveLength(3);
    expect(mirror.tabs.find((t) => t.id === "tab-a")?.href).toBe("/new");
    expect(mirror.tabs.find((t) => t.id === "tab-b")?.href).toBe("/inbox");
    expect(mirror.windows[0].activeTabId).toBe(tabId);
    // Focus moves through a tagged history entry, so the strip's navigation
    // effect treats it as a tab switch.
    expect(history.push).toHaveBeenCalledWith(destination.href, {
      tabId,
    });
    expect(mocks.persistWrite).toHaveBeenCalledOnce();
  });

  it("does not open when the mirror has no window, then seeds and opens", async () => {
    mocks.readMirror.mockReturnValue({ windows: [], tabs: [] });
    const seeded = snapshot();
    // reseedMirror applies the fetched snapshot to the mirror, which the open
    // path then reads back (mirrors the real tabsSync behavior).
    mocks.reseedMirror.mockImplementation(async () => {
      mocks.readMirror.mockReturnValue(seeded);
      return seeded;
    });

    const tabId = await openInNewBrowserTab(client(), destination);

    expect(tabId).toEqual(expect.any(String));
    expect(mocks.reseedMirror).toHaveBeenCalledOnce();
    expect(mocks.applyLocalTransform).toHaveBeenCalledOnce();
  });

  it("reports unavailable when there is no window even after a reseed", async () => {
    mocks.readMirror.mockReturnValue({ windows: [], tabs: [] });
    mocks.reseedMirror.mockResolvedValue({ windows: [], tabs: [] });

    await expect(
      openInNewBrowserTab(client(), destination),
    ).resolves.toBeNull();
    expect(mocks.applyLocalTransform).not.toHaveBeenCalled();
    expect(history.push).not.toHaveBeenCalled();
  });
});

describe("focusExistingTab", () => {
  const history = { location: { state: { tabId: "tab-b" } }, push: vi.fn() };

  beforeEach(() => {
    vi.clearAllMocks();
    history.location.state.tabId = "tab-b";
    mocks.getRouterOrNull.mockReturnValue({ history });
    mocks.readMirror.mockReturnValue(snapshot());
  });

  it("pushes a tagged history entry for an existing tab on the destination", () => {
    const push = vi.fn();
    mocks.getRouterOrNull.mockReturnValue({ history: { ...history, push } });

    expect(focusExistingTab({ href: "/new" })).toBe(true);
    expect(push).toHaveBeenCalledWith("/new", { tabId: "tab-a" });
  });

  it("reports a match without navigating when the active tab already shows it", () => {
    history.location.state.tabId = "tab-a";

    expect(focusExistingTab({ href: "/new" })).toBe(true);
  });

  it("keeps the active tab when an earlier tab shows the same destination", () => {
    const mirror = snapshot();
    mirror.tabs[0] = { ...mirror.tabs[0], href: "/tasks/task-1" };
    mirror.tabs[1] = { ...mirror.tabs[1], href: "/tasks/task-1" };
    mocks.readMirror.mockReturnValue(mirror);
    const push = vi.fn();
    mocks.getRouterOrNull.mockReturnValue({ history: { ...history, push } });

    expect(focusExistingTab({ href: "/tasks/task-1" })).toBe(true);
    expect(push).not.toHaveBeenCalled();
  });

  it("returns false when no tab shows the destination", () => {
    expect(focusExistingTab({ href: "/tasks/other" })).toBe(false);
  });

  it.each([
    { name: "the channel route form", href: "/spaces/chan-9/tasks/task-9" },
    { name: "a null href", href: null },
  ])("matches a task tab on its id across $name", ({ href }) => {
    const mirror = snapshot();
    mirror.tabs[0] = { ...mirror.tabs[0], href, taskId: "task-9" };
    mocks.readMirror.mockReturnValue(mirror);
    const push = vi.fn();
    mocks.getRouterOrNull.mockReturnValue({ history: { ...history, push } });

    expect(focusExistingTab({ href: "/tasks/task-9", taskId: "task-9" })).toBe(
      true,
    );
    expect(push).toHaveBeenCalledWith(href ?? "/tasks/task-9", {
      tabId: "tab-a",
    });
  });
});
