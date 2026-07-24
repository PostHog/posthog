import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/analytics", () => ({
  track: vi.fn(),
  setActiveTaskContext: vi.fn(),
}));

import { usePanelLayoutStore } from "./panelLayoutStore";
import {
  assertActiveTab,
  assertPanelLayout,
  assertTabCount,
  findPanelById,
  type GroupNode,
  getLayout,
  getPanelTree,
  openMultipleFiles,
  withRootGroup,
} from "./panelTestHelpers";

describe("panelLayoutStore", () => {
  beforeEach(() => {
    usePanelLayoutStore.getState().clearAllLayouts();
    localStorage.clear();
  });

  describe("initial state", () => {
    it("returns null for non-existent task", () => {
      const layout = usePanelLayoutStore.getState().getLayout("task-1");
      expect(layout).toBeNull();
    });

    it("creates default layout when task is initialized", () => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      const layout = usePanelLayoutStore.getState().getLayout("task-1");

      expect(layout).not.toBeNull();
      expect(layout?.panelTree.type).toBe("leaf");
    });

    it("creates default layout with correct structure", () => {
      usePanelLayoutStore.getState().initializeTask("task-1");

      const tree = getPanelTree("task-1");
      expect(tree.type).toBe("leaf");
      assertPanelLayout(tree, [
        {
          panelId: "main-panel",
          expectedTabs: ["logs", "shell"],
          activeTab: "logs",
        },
      ]);
    });
  });

  describe("openFile", () => {
    beforeEach(() => {
      usePanelLayoutStore.getState().initializeTask("task-1");
    });

    it("adds file tab to main panel by default", () => {
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");

      assertTabCount(getPanelTree("task-1"), "main-panel", 3);
      assertPanelLayout(getPanelTree("task-1"), [
        {
          panelId: "main-panel",
          expectedTabs: ["logs", "shell", "file-src/App.tsx"],
        },
      ]);
    });

    it("opens file in the focused panel", () => {
      usePanelLayoutStore
        .getState()
        .splitPanel("task-1", "logs", "main-panel", "main-panel", "right");

      const tree = getPanelTree("task-1");
      expect(tree.type).toBe("group");
      if (tree.type !== "group") return;

      const newPanelId = tree.children[1].id;
      usePanelLayoutStore.getState().setFocusedPanel("task-1", newPanelId);
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");

      assertPanelLayout(getPanelTree("task-1"), [
        {
          panelId: newPanelId,
          expectedTabs: ["logs", "file-src/App.tsx"],
          activeTab: "file-src/App.tsx",
        },
      ]);
      assertTabCount(getPanelTree("task-1"), "main-panel", 1);
    });

    it("falls back to main panel if focused panel does not exist", () => {
      // Set focus to a non-existent panel
      usePanelLayoutStore
        .getState()
        .setFocusedPanel("task-1", "non-existent-panel");

      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");

      // File should fall back to main-panel
      assertTabCount(getPanelTree("task-1"), "main-panel", 3);
      assertPanelLayout(getPanelTree("task-1"), [
        {
          panelId: "main-panel",
          expectedTabs: ["logs", "shell", "file-src/App.tsx"],
        },
      ]);
    });

    it("sets newly opened file as active", () => {
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");

      assertActiveTab(getPanelTree("task-1"), "main-panel", "file-src/App.tsx");
    });

    it("does not duplicate file if already open", () => {
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");

      const panel = findPanelById(getPanelTree("task-1"), "main-panel");
      const fileTabs = panel?.content.tabs.filter((t: { id: string }) =>
        t.id.startsWith("file-"),
      );
      expect(fileTabs).toHaveLength(1);
    });

    it("sets existing file as active when opened again", () => {
      openMultipleFiles("task-1", ["src/App.tsx", "src/Other.tsx"]);
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");

      assertActiveTab(getPanelTree("task-1"), "main-panel", "file-src/App.tsx");
    });

    it("tracks open files in metadata", () => {
      openMultipleFiles("task-1", ["src/App.tsx", "src/Other.tsx"]);

      const layout = getLayout("task-1");
      expect(layout.openFiles).toContain("src/App.tsx");
      expect(layout.openFiles).toContain("src/Other.tsx");
      expect(layout.openFiles).toHaveLength(2);
    });
  });

  describe("closeTab", () => {
    beforeEach(() => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      openMultipleFiles("task-1", ["src/App.tsx", "src/Other.tsx"]);
    });

    it("removes tab from panel", () => {
      usePanelLayoutStore
        .getState()
        .closeTab("task-1", "main-panel", "file-src/App.tsx");

      const panel = findPanelById(getPanelTree("task-1"), "main-panel");
      const fileTab = panel?.content.tabs.find(
        (t: { id: string }) => t.id === "file-src/App.tsx",
      );
      expect(fileTab).toBeUndefined();
    });

    it("removes file from metadata", () => {
      usePanelLayoutStore
        .getState()
        .closeTab("task-1", "main-panel", "file-src/App.tsx");

      const layout = getLayout("task-1");
      expect(layout.openFiles).not.toContain("src/App.tsx");
      expect(layout.openFiles).toContain("src/Other.tsx");
    });

    it("auto-selects next tab when closing active tab", () => {
      usePanelLayoutStore
        .getState()
        .closeTab("task-1", "main-panel", "file-src/Other.tsx");

      assertActiveTab(getPanelTree("task-1"), "main-panel", "file-src/App.tsx");
    });

    it("falls back to shell when last file tab closed", () => {
      usePanelLayoutStore
        .getState()
        .closeTab("task-1", "main-panel", "file-src/App.tsx");
      usePanelLayoutStore
        .getState()
        .closeTab("task-1", "main-panel", "file-src/Other.tsx");

      assertActiveTab(getPanelTree("task-1"), "main-panel", "shell");
    });
  });

  describe("setActiveTab", () => {
    beforeEach(() => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      openMultipleFiles("task-1", ["src/App.tsx", "src/Other.tsx"]);
    });

    it("changes active tab in panel", () => {
      usePanelLayoutStore
        .getState()
        .setActiveTab("task-1", "main-panel", "file-src/App.tsx");

      assertActiveTab(getPanelTree("task-1"), "main-panel", "file-src/App.tsx");
    });
  });

  describe("task isolation", () => {
    it("keeps tasks isolated from each other", () => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      usePanelLayoutStore.getState().initializeTask("task-2");

      openMultipleFiles("task-1", ["src/App.tsx"]);
      openMultipleFiles("task-2", ["src/Other.tsx"]);

      const layout1 = getLayout("task-1");
      const layout2 = getLayout("task-2");

      expect(layout1.openFiles).toContain("src/App.tsx");
      expect(layout1.openFiles).not.toContain("src/Other.tsx");

      expect(layout2.openFiles).toContain("src/Other.tsx");
      expect(layout2.openFiles).not.toContain("src/App.tsx");
    });
  });

  describe("panel size persistence", () => {
    beforeEach(() => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      openMultipleFiles("task-1", ["src/App.tsx", "src/Other.tsx"]);
      usePanelLayoutStore
        .getState()
        .splitPanel(
          "task-1",
          "file-src/App.tsx",
          "main-panel",
          "main-panel",
          "right",
        );
    });

    it("preserves custom panel sizes when opening a file", () => {
      const tree = getPanelTree("task-1");
      if (tree.type !== "group") throw new Error("Expected group");
      usePanelLayoutStore.getState().updateSizes("task-1", tree.id, [60, 40]);

      openMultipleFiles("task-1", ["src/Third.tsx"]);

      withRootGroup("task-1", (root) => {
        expect(root.sizes).toEqual([60, 40]);
      });
    });

    it("preserves custom panel sizes when switching tabs", () => {
      const tree = getPanelTree("task-1");
      if (tree.type !== "group") throw new Error("Expected group");
      usePanelLayoutStore.getState().updateSizes("task-1", tree.id, [55, 45]);
      usePanelLayoutStore
        .getState()
        .setActiveTab("task-1", "main-panel", "logs");

      withRootGroup("task-1", (root) => {
        expect(root.sizes).toEqual([55, 45]);
      });
    });

    it("preserves custom panel sizes when closing tabs", () => {
      const tree = getPanelTree("task-1");
      if (tree.type !== "group") throw new Error("Expected group");
      usePanelLayoutStore.getState().updateSizes("task-1", tree.id, [80, 20]);
      usePanelLayoutStore
        .getState()
        .closeTab("task-1", "main-panel", "file-src/Other.tsx");

      withRootGroup("task-1", (root) => {
        expect(root.sizes).toEqual([80, 20]);
      });
    });
  });

  describe("persistence", () => {
    it("persists state to localStorage", () => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");

      // Persistence is debounced; pagehide flushes pending writes.
      window.dispatchEvent(new Event("pagehide"));
      const storedData = localStorage.getItem("panel-layout-store");
      expect(storedData).not.toBeNull();

      const parsed = JSON.parse(storedData ?? "");
      expect(parsed.state.taskLayouts["task-1"]).toBeDefined();
      expect(parsed.state.taskLayouts["task-1"].openFiles).toContain(
        "src/App.tsx",
      );
    });

    it("restores state from localStorage", () => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");

      // Persistence is debounced; pagehide flushes pending writes.
      window.dispatchEvent(new Event("pagehide"));
      const storedData = localStorage.getItem("panel-layout-store");

      usePanelLayoutStore.getState().clearAllLayouts();
      expect(usePanelLayoutStore.getState().getLayout("task-1")).toBeNull();

      if (storedData) {
        localStorage.setItem("panel-layout-store", storedData);
        usePanelLayoutStore.persist.rehydrate();
      }

      const restoredLayout = getLayout("task-1");
      expect(restoredLayout.openFiles).toContain("src/App.tsx");
    });
  });

  describe("drag state", () => {
    beforeEach(() => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");
    });

    it("tracks dragging tab state", () => {
      usePanelLayoutStore
        .getState()
        .setDraggingTab("task-1", "file-src/App.tsx", "main-panel");

      const layout = getLayout("task-1");
      expect(layout.draggingTabId).toBe("file-src/App.tsx");
      expect(layout.draggingTabPanelId).toBe("main-panel");
    });

    it("clears dragging tab state", () => {
      usePanelLayoutStore
        .getState()
        .setDraggingTab("task-1", "file-src/App.tsx", "main-panel");
      usePanelLayoutStore.getState().clearDraggingTab("task-1");

      const layout = getLayout("task-1");
      expect(layout.draggingTabId).toBeNull();
      expect(layout.draggingTabPanelId).toBeNull();
    });

    it("isolates drag state between tasks", () => {
      usePanelLayoutStore.getState().initializeTask("task-2");
      usePanelLayoutStore
        .getState()
        .setDraggingTab("task-1", "file-src/App.tsx", "main-panel");

      const layout1 = getLayout("task-1");
      const layout2 = getLayout("task-2");

      expect(layout1.draggingTabId).toBe("file-src/App.tsx");
      expect(layout2.draggingTabId).toBeNull();
    });
  });

  describe("reorderTabs", () => {
    beforeEach(() => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      openMultipleFiles("task-1", [
        "src/App.tsx",
        "src/Other.tsx",
        "src/Third.tsx",
      ]);
    });

    it("reorders tabs within a panel", () => {
      // tabs: [logs, shell, file-src/App.tsx, file-src/Other.tsx, file-src/Third.tsx]
      // move index 2 to index 4
      usePanelLayoutStore.getState().reorderTabs("task-1", "main-panel", 2, 4);

      const panel = findPanelById(getPanelTree("task-1"), "main-panel");
      const tabIds = panel?.content.tabs.map((t: { id: string }) => t.id);
      expect(tabIds?.[2]).toBe("file-src/Other.tsx");
      expect(tabIds?.[4]).toBe("file-src/App.tsx");
    });

    it("preserves active tab after reorder", () => {
      usePanelLayoutStore
        .getState()
        .setActiveTab("task-1", "main-panel", "file-src/App.tsx");
      usePanelLayoutStore.getState().reorderTabs("task-1", "main-panel", 2, 4);

      assertActiveTab(getPanelTree("task-1"), "main-panel", "file-src/App.tsx");
    });
  });

  describe("moveTab", () => {
    let secondPanelId: string;

    beforeEach(() => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      openMultipleFiles("task-1", ["src/App.tsx", "src/Other.tsx"]);
      usePanelLayoutStore
        .getState()
        .splitPanel(
          "task-1",
          "file-src/Other.tsx",
          "main-panel",
          "main-panel",
          "right",
        );
      const tree = getPanelTree("task-1");
      if (tree.type !== "group") throw new Error("Expected group");
      secondPanelId = tree.children[1].id;
    });

    it("moves tab between panels", () => {
      usePanelLayoutStore
        .getState()
        .moveTab("task-1", "file-src/App.tsx", "main-panel", secondPanelId);

      const mainPanel = findPanelById(getPanelTree("task-1"), "main-panel");
      const secondPanel = findPanelById(getPanelTree("task-1"), secondPanelId);

      expect(
        mainPanel?.content.tabs.find((t) => t.id === "file-src/App.tsx"),
      ).toBeUndefined();
      expect(
        secondPanel?.content.tabs.find((t) => t.id === "file-src/App.tsx"),
      ).toBeDefined();
    });

    it("sets moved tab as active in target panel", () => {
      usePanelLayoutStore
        .getState()
        .moveTab("task-1", "file-src/App.tsx", "main-panel", secondPanelId);

      assertActiveTab(
        getPanelTree("task-1"),
        secondPanelId,
        "file-src/App.tsx",
      );
    });
  });

  describe("splitPanel", () => {
    beforeEach(() => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      openMultipleFiles("task-1", ["src/App.tsx", "src/Other.tsx"]);
    });

    it.each([
      ["right", "horizontal"],
      ["left", "horizontal"],
      ["top", "vertical"],
      ["bottom", "vertical"],
    ] as const)(
      "splits panel %s creates %s layout",
      (direction, expectedDirection) => {
        usePanelLayoutStore
          .getState()
          .splitPanel(
            "task-1",
            "file-src/App.tsx",
            "main-panel",
            "main-panel",
            direction,
          );

        const tree = getPanelTree("task-1");
        expect(tree.type).toBe("group");
        if (tree.type === "group") {
          expect(tree.direction).toBe(expectedDirection);
          expect(tree.children).toHaveLength(2);
        }
      },
    );

    it("moves tab to new split panel", () => {
      usePanelLayoutStore
        .getState()
        .splitPanel(
          "task-1",
          "file-src/App.tsx",
          "main-panel",
          "main-panel",
          "right",
        );

      const tree = getPanelTree("task-1");
      expect(tree.type).toBe("group");
      if (tree.type === "group") {
        const newPanel = tree.children[1];
        expect(newPanel.type).toBe("leaf");
        if (newPanel.type === "leaf") {
          expect(
            newPanel.content.tabs.some((t) => t.id === "file-src/App.tsx"),
          ).toBe(true);
          expect(newPanel.content.activeTabId).toBe("file-src/App.tsx");
        }
      }
    });
  });

  describe("updateSizes", () => {
    beforeEach(() => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      openMultipleFiles("task-1", ["src/App.tsx", "src/Other.tsx"]);
      usePanelLayoutStore
        .getState()
        .splitPanel(
          "task-1",
          "file-src/App.tsx",
          "main-panel",
          "main-panel",
          "right",
        );
    });

    it("updates panel group sizes", () => {
      const tree = getPanelTree("task-1");
      if (tree.type !== "group") throw new Error("Expected group");
      usePanelLayoutStore.getState().updateSizes("task-1", tree.id, [60, 40]);

      withRootGroup("task-1", (root: GroupNode) => {
        expect(root.sizes).toEqual([60, 40]);
      });
    });
  });

  describe("tree cleanup", () => {
    beforeEach(() => {
      usePanelLayoutStore.getState().initializeTask("task-1");
      openMultipleFiles("task-1", ["src/App.tsx", "src/Other.tsx"]);
    });

    it("removes empty panels after closing all tabs", () => {
      usePanelLayoutStore
        .getState()
        .splitPanel(
          "task-1",
          "file-src/App.tsx",
          "main-panel",
          "main-panel",
          "right",
        );

      const tree = getPanelTree("task-1");
      expect(tree.type).toBe("group");
      if (tree.type !== "group") return;

      const newPanel = tree.children[1];
      usePanelLayoutStore
        .getState()
        .closeTab("task-1", newPanel.id, "file-src/App.tsx");

      const updatedTree = getPanelTree("task-1");
      expect(updatedTree.type).toBe("leaf");
    });
  });

  describe("preview tabs", () => {
    beforeEach(() => {
      usePanelLayoutStore.getState().initializeTask("task-1");
    });

    it("creates preview tab by default when opening a file", () => {
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");

      const panel = findPanelById(getPanelTree("task-1"), "main-panel");
      const fileTab = panel?.content.tabs.find(
        (t: { id: string }) => t.id === "file-src/App.tsx",
      );
      expect(fileTab?.isPreview).toBe(true);
    });

    it("replaces existing preview tab when opening another file", () => {
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");
      usePanelLayoutStore.getState().openFile("task-1", "src/Other.tsx");

      const panel = findPanelById(getPanelTree("task-1"), "main-panel");
      const fileTabs = panel?.content.tabs.filter((t: { id: string }) =>
        t.id.startsWith("file-"),
      );
      expect(fileTabs).toHaveLength(1);
      expect(fileTabs?.[0].id).toBe("file-src/Other.tsx");
      expect(fileTabs?.[0].isPreview).toBe(true);
    });

    it("creates permanent tab when asPreview is false", () => {
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx", false);

      const panel = findPanelById(getPanelTree("task-1"), "main-panel");
      const fileTab = panel?.content.tabs.find(
        (t: { id: string }) => t.id === "file-src/App.tsx",
      );
      expect(fileTab?.isPreview).toBe(false);
    });

    it("keeps preview tab as preview when re-clicking same file", () => {
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");

      const panel = findPanelById(getPanelTree("task-1"), "main-panel");
      const fileTab = panel?.content.tabs.find(
        (t: { id: string }) => t.id === "file-src/App.tsx",
      );
      expect(fileTab?.isPreview).toBe(true);
    });

    it("pins preview tab when double-clicking (asPreview=false)", () => {
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx", false);

      const panel = findPanelById(getPanelTree("task-1"), "main-panel");
      const fileTab = panel?.content.tabs.find(
        (t: { id: string }) => t.id === "file-src/App.tsx",
      );
      expect(fileTab?.isPreview).toBe(false);
    });

    it("keepTab sets isPreview to false", () => {
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx");
      usePanelLayoutStore
        .getState()
        .keepTab("task-1", "main-panel", "file-src/App.tsx");

      const panel = findPanelById(getPanelTree("task-1"), "main-panel");
      const fileTab = panel?.content.tabs.find(
        (t: { id: string }) => t.id === "file-src/App.tsx",
      );
      expect(fileTab?.isPreview).toBe(false);
    });

    it("does not replace non-preview tabs when opening preview", () => {
      usePanelLayoutStore.getState().openFile("task-1", "src/App.tsx", false);
      usePanelLayoutStore.getState().openFile("task-1", "src/Other.tsx");

      const panel = findPanelById(getPanelTree("task-1"), "main-panel");
      const fileTabs = panel?.content.tabs.filter((t: { id: string }) =>
        t.id.startsWith("file-"),
      );
      expect(fileTabs).toHaveLength(2);
      expect(
        fileTabs?.find((t) => t.id === "file-src/App.tsx")?.isPreview,
      ).toBe(false);
      expect(
        fileTabs?.find((t) => t.id === "file-src/Other.tsx")?.isPreview,
      ).toBe(true);
    });
  });
});
