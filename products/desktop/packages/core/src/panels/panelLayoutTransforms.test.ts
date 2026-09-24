import { beforeEach, describe, expect, it } from "vitest";
import {
  addRecentFile,
  closePanel,
  closeTab,
  createInitialTaskLayout,
  openReadonlyTab,
  openTab,
  setActiveTab,
  splitPanelWithCopy,
} from "./panelLayoutTransforms";
import { createFileTabId, resetPanelIdCounter } from "./panelStoreHelpers";
import { collectLeafPanels, findTabInTree } from "./panelTree";
import type { LeafPanel, PanelNode, TaskLayout } from "./panelTypes";

function applyUpdates(
  layout: TaskLayout,
  updates: Partial<TaskLayout>,
): TaskLayout {
  return { ...layout, ...updates };
}

function collectNodeIds(node: PanelNode): string[] {
  return node.type === "leaf"
    ? [node.id]
    : [node.id, ...node.children.flatMap(collectNodeIds)];
}

function splitMainPanelRight(layout: TaskLayout): {
  next: TaskLayout;
  newPane: LeafPanel;
} {
  const next = applyUpdates(
    layout,
    splitPanelWithCopy(layout, "main-panel", "right"),
  );
  if (next.panelTree.type !== "group") throw new Error("expected a split");
  const newPane = next.panelTree.children[1];
  if (newPane.type !== "leaf") throw new Error("expected a leaf pane");
  return { next, newPane };
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

    it("keeps a file open while a copy of its tab survives", () => {
      const layout = createInitialTaskLayout();
      const tabId = createFileTabId("src/App.tsx");
      const opened = applyUpdates(layout, openTab(layout, tabId, false));
      const { next: split, newPane } = splitMainPanelRight(opened);

      const originalClosed = applyUpdates(
        split,
        closeTab(split, "main-panel", tabId),
      );
      expect(originalClosed.openFiles).toEqual(["src/App.tsx"]);

      const copyClosed = applyUpdates(
        originalClosed,
        closeTab(originalClosed, newPane.id, newPane.content.tabs[0].id),
      );
      expect(copyClosed.openFiles).toEqual([]);
    });
  });

  describe("splitPanelWithCopy", () => {
    it("shows a closeable copy of the active tab in a focused new pane and keeps the source tab", () => {
      const layout = createInitialTaskLayout();
      const { next, newPane } = splitMainPanelRight(layout);

      expect(findTabInTree(next.panelTree, "logs")?.panelId).toBe("main-panel");
      const copy = newPane.content.tabs[0];
      expect(copy.id).not.toBe("logs");
      expect(copy).toMatchObject({
        label: "Chat",
        data: { type: "logs" },
        closeable: true,
      });
      expect(newPane.content.activeTabId).toBe(copy.id);
      expect(next.focusedPanelId).toBe(newPane.id);
    });

    it("gives every copy and every pane an id of its own, also after the id counter restarts", () => {
      const layout = createInitialTaskLayout();
      const { next: once } = splitMainPanelRight(layout);
      resetPanelIdCounter();
      const { next: twice } = splitMainPanelRight(once);

      const nodeIds = collectNodeIds(twice.panelTree);
      expect(new Set(nodeIds).size).toBe(nodeIds.length);
      const tabIds = collectLeafPanels(twice.panelTree).flatMap((leaf) =>
        leaf.content.tabs.map((tab) => tab.id),
      );
      expect(new Set(tabIds).size).toBe(tabIds.length);
    });

    it.each([
      ["right", "horizontal", 1],
      ["left", "horizontal", 0],
      ["bottom", "vertical", 1],
      ["top", "vertical", 0],
    ] as const)(
      "places the new pane %s of the source",
      (direction, expectedDirection, newPaneIndex) => {
        const layout = createInitialTaskLayout();
        const next = applyUpdates(
          layout,
          splitPanelWithCopy(layout, "main-panel", direction),
        );

        if (next.panelTree.type !== "group")
          throw new Error("expected a split");
        expect(next.panelTree.direction).toBe(expectedDirection);
        expect(next.panelTree.children[newPaneIndex].id).toBe(
          next.focusedPanelId,
        );
        expect(next.panelTree.children[1 - newPaneIndex].id).toBe("main-panel");
      },
    );

    it("opens a fresh terminal instead of a second view of the same pty", () => {
      const layout = createInitialTaskLayout();
      const onShell = applyUpdates(
        layout,
        setActiveTab(layout, "main-panel", "shell"),
      );
      const { newPane } = splitMainPanelRight(onShell);

      const tab = newPane.content.tabs[0];
      expect(tab.data.type).toBe("terminal");
      if (tab.data.type !== "terminal") return;
      expect(tab.data.terminalId).toBe(tab.id);
      expect(tab.data.terminalId).not.toBe("shell");
    });
  });

  describe("closePanel", () => {
    it("closes the pane's tabs, collapses the split and focuses the neighbor", () => {
      const layout = createInitialTaskLayout();
      const { next: split, newPane } = splitMainPanelRight(layout);
      const appTab = createFileTabId("src/App.tsx");
      const otherTab = createFileTabId("src/Other.tsx");
      const withOther = applyUpdates(
        split,
        openTab(split, otherTab, false, newPane.id),
      );
      const withBoth = applyUpdates(
        withOther,
        openTab(withOther, appTab, false, "main-panel"),
      );

      const closed = applyUpdates(withBoth, closePanel(withBoth, newPane.id));

      expect(closed.panelTree).toMatchObject({
        type: "leaf",
        id: "main-panel",
      });
      expect(findTabInTree(closed.panelTree, otherTab)).toBeNull();
      expect(findTabInTree(closed.panelTree, appTab)).not.toBeNull();
      expect(closed.focusedPanelId).toBe("main-panel");
      expect(closed.openFiles).toEqual(["src/App.tsx"]);
    });

    it("moves tabs that cannot close into the neighbor, which then takes main-placed artifacts", () => {
      const layout = createInitialTaskLayout();
      const { next: split, newPane } = splitMainPanelRight(layout);

      const closed = applyUpdates(split, closePanel(split, "main-panel"));

      expect(closed.panelTree.type).toBe("leaf");
      if (closed.panelTree.type !== "leaf") return;
      expect(closed.panelTree.id).toBe(newPane.id);
      expect(closed.panelTree.content.tabs.map((tab) => tab.id)).toEqual([
        newPane.content.tabs[0].id,
        "logs",
      ]);
      expect(closed.focusedPanelId).toBe(newPane.id);

      const opened = applyUpdates(
        closed,
        openReadonlyTab(
          closed,
          "artifact-1",
          "report.md",
          { type: "artifact", runId: "run-1", artifactId: "1" },
          "main",
        ),
      );
      expect(findTabInTree(opened.panelTree, "artifact-1")?.panelId).toBe(
        newPane.id,
      );
    });

    it("keeps the last pane and its pinned tabs", () => {
      const layout = createInitialTaskLayout();

      const closed = applyUpdates(layout, closePanel(layout, "main-panel"));

      expect(closed.panelTree).toMatchObject({
        type: "leaf",
        id: "main-panel",
      });
      if (closed.panelTree.type !== "leaf") return;
      expect(closed.panelTree.content.tabs.map((tab) => tab.id)).toEqual([
        "logs",
      ]);
      expect(closed.panelTree.content.activeTabId).toBe("logs");
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
