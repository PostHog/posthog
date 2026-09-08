import { beforeEach, describe, expect, it } from "vitest";
import {
  addBrowserTab,
  addRecentFile,
  closeTab,
  createInitialTaskLayout,
  openTab,
  updateBrowserTabUrl,
} from "./panelLayoutTransforms";
import { createFileTabId, resetPanelIdCounter } from "./panelStoreHelpers";
import { findTabInTree } from "./panelTree";
import type { TaskLayout } from "./panelTypes";

function applyUpdates(
  layout: TaskLayout,
  updates: Partial<TaskLayout>,
): TaskLayout {
  return { ...layout, ...updates };
}

describe("panelLayoutTransforms", () => {
  beforeEach(() => {
    resetPanelIdCounter();
  });

  describe("createInitialTaskLayout", () => {
    it("creates a leaf main panel with logs and shell tabs", () => {
      const layout = createInitialTaskLayout();
      expect(layout.panelTree.type).toBe("leaf");
      if (layout.panelTree.type !== "leaf") return;
      expect(layout.panelTree.content.tabs.map((t) => t.id)).toEqual([
        "logs",
        "shell",
      ]);
      expect(layout.panelTree.content.activeTabId).toBe("logs");
    });
  });

  describe("openTab", () => {
    it("adds a new file tab to the main panel", () => {
      const layout = createInitialTaskLayout();
      const tabId = createFileTabId("src/App.tsx");
      const next = applyUpdates(layout, openTab(layout, tabId, false));

      expect(findTabInTree(next.panelTree, tabId)).not.toBeNull();
      expect(next.panelTree.type).toBe("leaf");
      if (next.panelTree.type !== "leaf") return;
      expect(next.panelTree.content.tabs.length).toBe(3);
      expect(next.panelTree.content.activeTabId).toBe(tabId);
    });

    it("activates an existing tab instead of duplicating it", () => {
      const layout = createInitialTaskLayout();
      const tabId = createFileTabId("src/App.tsx");
      const opened = applyUpdates(layout, openTab(layout, tabId, false));
      const reopened = applyUpdates(opened, openTab(opened, tabId, false));

      if (reopened.panelTree.type !== "leaf") return;
      const occurrences = reopened.panelTree.content.tabs.filter(
        (t) => t.id === tabId,
      );
      expect(occurrences.length).toBe(1);
    });
  });

  describe("closeTab", () => {
    it("removes the tab and selects a fallback", () => {
      const layout = createInitialTaskLayout();
      const tabId = createFileTabId("src/App.tsx");
      const opened = applyUpdates(layout, openTab(layout, tabId, false));
      const closed = applyUpdates(
        opened,
        closeTab(opened, "main-panel", tabId),
      );

      expect(findTabInTree(closed.panelTree, tabId)).toBeNull();
    });
  });

  describe("addBrowserTab", () => {
    it("adds an empty-url browser tab and activates it", () => {
      const layout = createInitialTaskLayout();
      const added = applyUpdates(layout, addBrowserTab(layout, "main-panel"));

      expect(added.panelTree.type).toBe("leaf");
      if (added.panelTree.type !== "leaf") return;
      const tab = added.panelTree.content.tabs.at(-1);
      expect(tab?.data).toEqual({
        type: "browser",
        browserId: tab?.id,
        url: "",
      });
      expect(tab?.closeable).toBe(true);
      expect(added.panelTree.content.activeTabId).toBe(tab?.id);
    });

    it("does nothing for an unknown panel", () => {
      const layout = createInitialTaskLayout();
      const result = applyUpdates(layout, addBrowserTab(layout, "nope"));
      expect(result.panelTree).toEqual(layout.panelTree);
    });
  });

  describe("updateBrowserTabUrl", () => {
    it("persists the current page into the tab data", () => {
      const layout = createInitialTaskLayout();
      const added = applyUpdates(layout, addBrowserTab(layout, "main-panel"));
      const tabId =
        added.panelTree.type === "leaf"
          ? (added.panelTree.content.tabs.at(-1)?.id ?? "")
          : "";

      const updated = applyUpdates(
        added,
        updateBrowserTabUrl(added, tabId, "http://localhost:8000/app"),
      );
      const tab = findTabInTree(updated.panelTree, tabId)?.tab;
      expect(tab?.data).toEqual({
        type: "browser",
        browserId: tabId,
        url: "http://localhost:8000/app",
      });
    });

    it("ignores unknown tabs and non-browser tabs", () => {
      const layout = createInitialTaskLayout();
      expect(updateBrowserTabUrl(layout, "nope", "https://x.example")).toEqual(
        {},
      );
      // "logs" exists but is not a browser tab — its data must not change.
      const updated = applyUpdates(
        layout,
        updateBrowserTabUrl(layout, "logs", "https://x.example"),
      );
      expect(findTabInTree(updated.panelTree, "logs")?.tab.data).toEqual({
        type: "logs",
      });
    });
  });

  describe("addRecentFile", () => {
    it("dedupes and prepends, capping at the max", () => {
      const result = addRecentFile(["b", "a"], "a");
      expect(result).toEqual(["a", "b"]);
    });

    it("caps at MAX_RECENT_FILES", () => {
      const initial = Array.from({ length: 12 }, (_, i) => `f${i}`);
      const result = addRecentFile(initial, "new");
      expect(result.length).toBe(10);
      expect(result[0]).toBe("new");
    });
  });
});
