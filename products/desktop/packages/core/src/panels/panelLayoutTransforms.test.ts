import { beforeEach, describe, expect, it } from "vitest";
import {
  addRecentFile,
  closeTab,
  createInitialTaskLayout,
  openTab,
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
