import type { TabsSnapshot } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { requestTabSelection } from "./tabSelection";

const snapshot: TabsSnapshot = {
  windows: [
    {
      id: "window-1",
      isPrimary: true,
      bounds: null,
      activeTabId: "url-tab",
    },
  ],
  tabs: [
    {
      id: "url-tab",
      windowId: "window-1",
      href: "/activity?taskId=task-1",
      viewState: null,
      dashboardId: null,
      taskId: "task-1",
      channelId: null,
      channelSection: null,
      appView: "activity",
      position: 1000,
      scrollState: null,
      createdAt: 1,
      lastActiveAt: 1,
    },
    {
      id: "new-tab",
      windowId: "window-1",
      href: "/spaces",
      viewState: { title: "New tab" },
      dashboardId: null,
      taskId: null,
      channelId: null,
      channelSection: null,
      appView: null,
      position: 2000,
      scrollState: null,
      createdAt: 2,
      lastActiveAt: 2,
    },
  ],
};

describe("requestTabSelection", () => {
  it("leaves the settled URL tab untouched until the selected route lands", () => {
    const navigate = vi.fn();
    const beforeSelection = structuredClone(snapshot);

    requestTabSelection(snapshot, "window-1", "new-tab", navigate);

    expect(snapshot).toEqual(beforeSelection);
    expect(navigate).toHaveBeenCalledOnce();
    expect(navigate).toHaveBeenCalledWith(snapshot.tabs[1]);
  });

  it("ignores a tab owned by another window", () => {
    const navigate = vi.fn();

    requestTabSelection(snapshot, "window-2", "new-tab", navigate);

    expect(navigate).not.toHaveBeenCalled();
  });
});
