import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { usePanelLayoutStore } from "../panels/panelLayoutStore";
import { useBrowserViewCleanup } from "./useBrowserViewCleanup";

const destroyMutate = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({
    embeddedBrowser: { destroy: { mutate: destroyMutate } },
  }),
}));

vi.mock("../../shell/useHostCapabilities", () => ({
  useHostCapabilities: () => ({ localWorkspaces: true, embeddedBrowser: true }),
}));

function layoutWithBrowserTabs(tabIds: string[]) {
  return {
    panelTree: {
      type: "leaf" as const,
      id: "main-panel",
      content: {
        id: "main-panel",
        activeTabId: tabIds[0] ?? "logs",
        tabs: tabIds.map((id) => ({
          id,
          label: "Browser",
          data: { type: "browser" as const, browserId: id, url: "" },
        })),
      },
    },
    openFiles: [],
    recentFiles: [],
    draggingTabId: null,
    draggingTabPanelId: null,
    focusedPanelId: null,
  };
}

describe("useBrowserViewCleanup", () => {
  afterEach(() => {
    usePanelLayoutStore.setState({ taskLayouts: {} });
    destroyMutate.mockClear();
  });

  it("destroys the view of a tab that leaves the layout, however it left", () => {
    usePanelLayoutStore.setState({
      taskLayouts: { t1: layoutWithBrowserTabs(["browser-1", "browser-2"]) },
    });
    renderHook(() => useBrowserViewCleanup("t1"));

    // close-others style removal: browser-2 disappears without an onClose
    usePanelLayoutStore.setState({
      taskLayouts: { t1: layoutWithBrowserTabs(["browser-1"]) },
    });

    expect(destroyMutate).toHaveBeenCalledTimes(1);
    expect(destroyMutate).toHaveBeenCalledWith({
      viewId: "task-browser:t1:browser-2",
    });
  });

  it("ignores other tasks' layout changes", () => {
    usePanelLayoutStore.setState({
      taskLayouts: {
        t1: layoutWithBrowserTabs(["browser-1"]),
        t2: layoutWithBrowserTabs(["browser-9"]),
      },
    });
    renderHook(() => useBrowserViewCleanup("t1"));

    usePanelLayoutStore.setState({
      taskLayouts: { t1: layoutWithBrowserTabs(["browser-1"]) },
    });

    expect(destroyMutate).not.toHaveBeenCalled();
  });

  it("stops reconciling after unmount (task switch must not destroy)", () => {
    usePanelLayoutStore.setState({
      taskLayouts: { t1: layoutWithBrowserTabs(["browser-1"]) },
    });
    const { unmount } = renderHook(() => useBrowserViewCleanup("t1"));
    unmount();

    usePanelLayoutStore.setState({ taskLayouts: {} });
    expect(destroyMutate).not.toHaveBeenCalled();
  });
});
