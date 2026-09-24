import { DEFAULT_PANEL_IDS, DEFAULT_TAB_IDS } from "./panelConstants";
import {
  addNewTabToPanel,
  applyCleanupWithFallback,
  generatePanelId,
  getLeafPanel,
  getSplitConfig,
  selectNextTabAfterClose,
  updateMetadataForTab,
} from "./panelStoreHelpers";
import {
  addTabToPanel,
  cleanupNode,
  findNeighborLeaf,
  findTabInPanel,
  findTabInTree,
  removeTabFromPanel,
  updateTreeNode,
} from "./panelTree";
import type {
  PanelNode,
  SplitDirection,
  Tab,
  TabData,
  TaskLayout,
} from "./panelTypes";

const MAX_RECENT_FILES = 10;

function createTerminalTab(cwd = ""): Tab {
  const tabId = `shell-${Date.now()}`;
  return {
    id: tabId,
    label: "Terminal",
    data: { type: "terminal", terminalId: tabId, cwd },
    component: null,
    draggable: true,
    closeable: true,
  };
}

function createDefaultPanelTree(): PanelNode {
  return {
    type: "leaf",
    id: DEFAULT_PANEL_IDS.MAIN_PANEL,
    content: {
      id: DEFAULT_PANEL_IDS.MAIN_PANEL,
      tabs: [
        {
          id: DEFAULT_TAB_IDS.LOGS,
          label: "Chat",
          data: { type: "logs" },
          component: null,
          closeable: false,
          draggable: true,
        },
        {
          id: DEFAULT_TAB_IDS.SHELL,
          label: "Terminal",
          data: {
            type: "terminal",
            terminalId: DEFAULT_TAB_IDS.SHELL,
            cwd: "",
          },
          component: null,
          closeable: true,
          draggable: true,
        },
      ],
      activeTabId: DEFAULT_TAB_IDS.LOGS,
      showTabs: true,
      droppable: true,
    },
  };
}

export function createInitialTaskLayout(): TaskLayout {
  return {
    panelTree: createDefaultPanelTree(),
    openFiles: [],
    recentFiles: [],
    draggingTabId: null,
    draggingTabPanelId: null,
    focusedPanelId: DEFAULT_PANEL_IDS.MAIN_PANEL,
  };
}

export function openTab(
  layout: TaskLayout,
  tabId: string,
  asPreview = true,
  targetPanelId?: string,
): Partial<TaskLayout> {
  const existingTab = findTabInTree(layout.panelTree, tabId);

  if (existingTab) {
    const updatedTree = updateTreeNode(
      layout.panelTree,
      existingTab.panelId,
      (panel) => {
        if (panel.type !== "leaf") return panel;
        return {
          ...panel,
          content: {
            ...panel.content,
            tabs: asPreview
              ? panel.content.tabs
              : panel.content.tabs.map((tab) =>
                  tab.id === tabId ? { ...tab, isPreview: false } : tab,
                ),
            activeTabId: tabId,
          },
        };
      },
    );

    return { panelTree: updatedTree };
  }

  const resolvedPanelId =
    targetPanelId ?? layout.focusedPanelId ?? DEFAULT_PANEL_IDS.MAIN_PANEL;
  let targetPanel = getLeafPanel(layout.panelTree, resolvedPanelId);

  if (!targetPanel) {
    targetPanel = getLeafPanel(layout.panelTree, DEFAULT_PANEL_IDS.MAIN_PANEL);
  }
  if (!targetPanel) return {};

  const panelId = targetPanel.id;
  const updatedTree = updateTreeNode(layout.panelTree, panelId, (panel) =>
    addNewTabToPanel(panel, tabId, true, asPreview),
  );

  const metadata = updateMetadataForTab(layout, tabId, "add");

  return {
    panelTree: updatedTree,
    ...metadata,
  };
}

function findNonMainLeafPanel(node: PanelNode): PanelNode | null {
  if (node.type === "leaf") {
    return node.id !== DEFAULT_PANEL_IDS.MAIN_PANEL ? node : null;
  }
  if (node.type === "group") {
    for (const child of node.children) {
      const found = findNonMainLeafPanel(child);
      if (found) return found;
    }
  }
  return null;
}

export function openTabInSplit(
  layout: TaskLayout,
  tabId: string,
  asPreview = true,
): Partial<TaskLayout> {
  const existingTab = findTabInTree(layout.panelTree, tabId);

  if (existingTab) {
    const updatedTree = updateTreeNode(
      layout.panelTree,
      existingTab.panelId,
      (panel) => {
        if (panel.type !== "leaf") return panel;
        return {
          ...panel,
          content: {
            ...panel.content,
            tabs: asPreview
              ? panel.content.tabs
              : panel.content.tabs.map((tab) =>
                  tab.id === tabId ? { ...tab, isPreview: false } : tab,
                ),
            activeTabId: tabId,
          },
        };
      },
    );

    return { panelTree: updatedTree };
  }

  const nonMainPanel = findNonMainLeafPanel(layout.panelTree);

  if (nonMainPanel) {
    const updatedTree = updateTreeNode(
      layout.panelTree,
      nonMainPanel.id,
      (panel) => addNewTabToPanel(panel, tabId, true, asPreview),
    );

    const metadata = updateMetadataForTab(layout, tabId, "add");
    return { panelTree: updatedTree, ...metadata };
  }

  const newPanelId = generatePanelId(layout.panelTree);
  const newPanel: PanelNode = {
    type: "leaf",
    id: newPanelId,
    content: {
      id: newPanelId,
      tabs: [],
      activeTabId: "",
      showTabs: true,
      droppable: true,
    },
  };

  const mainPanel = getLeafPanel(
    layout.panelTree,
    DEFAULT_PANEL_IDS.MAIN_PANEL,
  );
  if (!mainPanel) return {};

  const splitTree = updateTreeNode(
    layout.panelTree,
    DEFAULT_PANEL_IDS.MAIN_PANEL,
    (panel) => ({
      type: "group" as const,
      id: generatePanelId(layout.panelTree),
      direction: "horizontal" as const,
      sizes: [50, 50],
      children: [panel, newPanel],
    }),
  );

  const finalTree = updateTreeNode(splitTree, newPanelId, (panel) =>
    addNewTabToPanel(panel, tabId, true, asPreview),
  );

  const metadata = updateMetadataForTab(layout, tabId, "add");
  return { panelTree: finalTree, focusedPanelId: newPanelId, ...metadata };
}

// Opens read-only content with inline tab data. Most callers use the right-side
// split; generated artifacts opt into the main panel beside Chat. Re-opening
// the same tab id just activates the existing tab.
export function openReadonlyTab(
  layout: TaskLayout,
  tabId: string,
  label: string,
  data: TabData,
  placement: "main" | "split" = "split",
): Partial<TaskLayout> {
  const buildTab = (): Tab => ({
    id: tabId,
    label,
    data,
    component: null,
    draggable: true,
    closeable: true,
  });

  const existingTab = findTabInTree(layout.panelTree, tabId);
  if (existingTab) {
    const updatedTree = updateTreeNode(
      layout.panelTree,
      existingTab.panelId,
      (panel) => {
        if (panel.type !== "leaf") return panel;
        return {
          ...panel,
          content: { ...panel.content, activeTabId: tabId },
        };
      },
    );
    return { panelTree: updatedTree, focusedPanelId: existingTab.panelId };
  }

  if (placement === "main") {
    // closePanel can remove the main pane, so fall back to a surviving one.
    const mainPanel =
      getLeafPanel(layout.panelTree, DEFAULT_PANEL_IDS.MAIN_PANEL) ??
      findNonMainLeafPanel(layout.panelTree);
    if (!mainPanel) return {};
    const panelTree = updateTreeNode(
      layout.panelTree,
      mainPanel.id,
      (panel) => {
        if (panel.type !== "leaf") return panel;
        return {
          ...panel,
          content: {
            ...panel.content,
            tabs: [...panel.content.tabs, buildTab()],
            activeTabId: tabId,
          },
        };
      },
    );
    return { panelTree, focusedPanelId: mainPanel.id };
  }

  const nonMainPanel = findNonMainLeafPanel(layout.panelTree);
  if (nonMainPanel) {
    const updatedTree = updateTreeNode(
      layout.panelTree,
      nonMainPanel.id,
      (panel) => {
        if (panel.type !== "leaf") return panel;
        return {
          ...panel,
          content: {
            ...panel.content,
            tabs: [...panel.content.tabs, buildTab()],
            activeTabId: tabId,
          },
        };
      },
    );
    return { panelTree: updatedTree, focusedPanelId: nonMainPanel.id };
  }

  const mainPanel = getLeafPanel(
    layout.panelTree,
    DEFAULT_PANEL_IDS.MAIN_PANEL,
  );
  if (!mainPanel) return {};

  const newPanelId = generatePanelId(layout.panelTree);
  const newPanel: PanelNode = {
    type: "leaf",
    id: newPanelId,
    content: {
      id: newPanelId,
      tabs: [buildTab()],
      activeTabId: tabId,
      showTabs: true,
      droppable: true,
    },
  };

  const splitTree = updateTreeNode(
    layout.panelTree,
    DEFAULT_PANEL_IDS.MAIN_PANEL,
    (panel) => ({
      type: "group" as const,
      id: generatePanelId(layout.panelTree),
      direction: "horizontal" as const,
      sizes: [50, 50],
      children: [panel, newPanel],
    }),
  );

  return { panelTree: splitTree, focusedPanelId: newPanelId };
}

export function addRecentFile(
  recentFiles: string[] | undefined,
  filePath: string,
): string[] {
  return [filePath, ...(recentFiles || []).filter((f) => f !== filePath)].slice(
    0,
    MAX_RECENT_FILES,
  );
}

export function keepTab(layout: TaskLayout, panelId: string, tabId: string) {
  const updatedTree = updateTreeNode(layout.panelTree, panelId, (panel) => {
    if (panel.type !== "leaf") return panel;
    return {
      ...panel,
      content: {
        ...panel.content,
        tabs: panel.content.tabs.map((tab) =>
          tab.id === tabId ? { ...tab, isPreview: false } : tab,
        ),
      },
    };
  });
  return { panelTree: updatedTree };
}

export function closeTab(
  layout: TaskLayout,
  panelId: string,
  tabId: string,
): Partial<TaskLayout> {
  const updatedTree = updateTreeNode(layout.panelTree, panelId, (panel) => {
    if (panel.type !== "leaf") return panel;

    const tabIndex = panel.content.tabs.findIndex((t) => t.id === tabId);
    const remainingTabs = panel.content.tabs.filter((t) => t.id !== tabId);

    const newActiveTabId = selectNextTabAfterClose(
      remainingTabs,
      tabIndex,
      panel.content.activeTabId,
      tabId,
    );

    return {
      ...panel,
      content: {
        ...panel.content,
        tabs: remainingTabs,
        activeTabId: newActiveTabId,
      },
    };
  });

  const cleanedTree = applyCleanupWithFallback(
    cleanupNode(updatedTree),
    layout.panelTree,
  );
  const metadata = updateMetadataForTab(layout, tabId, "remove");

  return {
    panelTree: cleanedTree,
    ...metadata,
  };
}

export function closeOtherTabs(
  layout: TaskLayout,
  panelId: string,
  tabId: string,
): Partial<TaskLayout> {
  const updatedTree = updateTreeNode(layout.panelTree, panelId, (panel) => {
    if (panel.type !== "leaf") return panel;

    const remainingTabs = panel.content.tabs.filter(
      (t) => t.id === tabId || t.closeable === false,
    );

    return {
      ...panel,
      content: {
        ...panel.content,
        tabs: remainingTabs,
        activeTabId: tabId,
      },
    };
  });

  return { panelTree: updatedTree };
}

export function closeTabsToRight(
  layout: TaskLayout,
  panelId: string,
  tabId: string,
): Partial<TaskLayout> {
  const updatedTree = updateTreeNode(layout.panelTree, panelId, (panel) => {
    if (panel.type !== "leaf") return panel;

    const tabIndex = panel.content.tabs.findIndex((t) => t.id === tabId);
    if (tabIndex === -1) return panel;

    const remainingTabs = panel.content.tabs.filter(
      (t, index) => index <= tabIndex || t.closeable === false,
    );

    return {
      ...panel,
      content: {
        ...panel.content,
        tabs: remainingTabs,
        activeTabId: tabId,
      },
    };
  });

  return { panelTree: updatedTree };
}

export function reorderTabs(
  layout: TaskLayout,
  panelId: string,
  sourceIndex: number,
  targetIndex: number,
): Partial<TaskLayout> {
  const updatedTree = updateTreeNode(layout.panelTree, panelId, (panel) => {
    if (panel.type !== "leaf") return panel;

    const tabs = [...panel.content.tabs];
    const [removed] = tabs.splice(sourceIndex, 1);
    tabs.splice(targetIndex, 0, removed);

    return {
      ...panel,
      content: {
        ...panel.content,
        tabs,
      },
    };
  });

  return { panelTree: updatedTree };
}

export function moveTab(
  layout: TaskLayout,
  tabId: string,
  sourcePanelId: string,
  targetPanelId: string,
): Partial<TaskLayout> {
  const sourcePanel = getLeafPanel(layout.panelTree, sourcePanelId);
  if (!sourcePanel) return {};

  const tab = findTabInPanel(sourcePanel, tabId);
  if (!tab) return {};

  const treeAfterRemove = updateTreeNode(
    layout.panelTree,
    sourcePanelId,
    (panel) => removeTabFromPanel(panel, tabId),
  );

  const treeAfterAdd = updateTreeNode(treeAfterRemove, targetPanelId, (panel) =>
    addTabToPanel(panel, tab),
  );

  const cleanedTree = applyCleanupWithFallback(
    cleanupNode(treeAfterAdd),
    layout.panelTree,
  );

  const focusedPanelId =
    layout.focusedPanelId === sourcePanelId
      ? targetPanelId
      : layout.focusedPanelId;

  return { panelTree: cleanedTree, focusedPanelId };
}

export function splitPanelTree(
  layout: TaskLayout,
  tabId: string,
  sourcePanelId: string,
  targetPanelId: string,
  direction: SplitDirection,
): Partial<TaskLayout> {
  const sourcePanel = getLeafPanel(layout.panelTree, sourcePanelId);
  if (!sourcePanel) return {};

  const targetPanel = getLeafPanel(layout.panelTree, targetPanelId);
  if (!targetPanel) return {};

  const tab = findTabInPanel(sourcePanel, tabId);
  if (!tab) return {};

  if (sourcePanelId === targetPanelId && targetPanel.content.tabs.length <= 1) {
    const singleTabConfig = getSplitConfig(direction);
    const newPanelId = generatePanelId(layout.panelTree);
    const terminalTab = createTerminalTab();
    const newPanel: PanelNode = {
      type: "leaf",
      id: newPanelId,
      content: {
        id: newPanelId,
        tabs: [terminalTab],
        activeTabId: terminalTab.id,
        showTabs: true,
        droppable: true,
      },
    };

    const updatedTree = updateTreeNode(
      layout.panelTree,
      targetPanelId,
      (panel) => ({
        type: "group" as const,
        id: generatePanelId(layout.panelTree),
        direction: singleTabConfig.splitDirection,
        sizes: [50, 50],
        children: singleTabConfig.isAfter
          ? [panel, newPanel]
          : [newPanel, panel],
      }),
    );

    return { panelTree: updatedTree, focusedPanelId: newPanelId };
  }

  const config = getSplitConfig(direction);
  const newPanelId = generatePanelId(layout.panelTree);
  const newPanel: PanelNode = {
    type: "leaf",
    id: newPanelId,
    content: {
      id: newPanelId,
      tabs: [tab],
      activeTabId: tab.id,
      showTabs: true,
      droppable: true,
    },
  };

  const treeAfterRemove = updateTreeNode(
    layout.panelTree,
    sourcePanelId,
    (panel) => removeTabFromPanel(panel, tabId),
  );

  const updatedTree = updateTreeNode(
    treeAfterRemove,
    targetPanelId,
    (panel) => {
      const newGroup: PanelNode = {
        type: "group",
        id: generatePanelId(layout.panelTree),
        direction: config.splitDirection,
        sizes: [50, 50],
        children: config.isAfter ? [panel, newPanel] : [newPanel, panel],
      };
      return newGroup;
    },
  );

  const cleanedTree = applyCleanupWithFallback(
    cleanupNode(updatedTree),
    layout.panelTree,
  );

  return { panelTree: cleanedTree };
}

const COPY_TAB_ID_PATTERN = /^copy-\d+:(.*)$/;

// Tab ids key React lists, drag sources and findTabInTree, so a second tab
// with the source id would collide across panes. The copy gets its own id;
// the "copy-" prefix keeps it out of the file-tab id parsing in
// updateMetadataForTab, which tracks open files by the source tab only.
function createCopyTabId(tree: PanelNode, sourceTabId: string): string {
  const baseId = sourceTabId.match(COPY_TAB_ID_PATTERN)?.[1] ?? sourceTabId;
  let copyNumber = 2;
  while (findTabInTree(tree, `copy-${copyNumber}:${baseId}`)) {
    copyNumber++;
  }
  return `copy-${copyNumber}:${baseId}`;
}

function copyTab(tree: PanelNode, tab: Tab): Tab {
  // A terminal tab owns one pty, and two views of the same pty would fight
  // over its input. Open a fresh shell in the same directory instead, as
  // VS Code does when it splits a terminal.
  if (tab.data.type === "terminal") {
    return createTerminalTab(tab.data.cwd);
  }
  // The source may be pinned (Chat) or a preview; the copy is an ordinary tab.
  return {
    ...tab,
    id: createCopyTabId(tree, tab.id),
    closeable: true,
    isPreview: false,
  };
}

/**
 * The VS Code "Split editor" behavior: a new pane beside the source pane that
 * shows a copy of the source pane's active tab, while the source pane keeps
 * its tab. Focus moves to the new pane.
 */
export function splitPanelWithCopy(
  layout: TaskLayout,
  panelId: string,
  direction: SplitDirection,
): Partial<TaskLayout> {
  const sourcePanel = getLeafPanel(layout.panelTree, panelId);
  if (!sourcePanel) return {};

  const activeTab = findTabInPanel(
    sourcePanel,
    sourcePanel.content.activeTabId,
  );
  if (!activeTab) return {};

  const copy = copyTab(layout.panelTree, activeTab);
  const config = getSplitConfig(direction);
  const newPanelId = generatePanelId(layout.panelTree);
  const newPanel: PanelNode = {
    type: "leaf",
    id: newPanelId,
    content: {
      id: newPanelId,
      tabs: [copy],
      activeTabId: copy.id,
      showTabs: true,
      droppable: true,
    },
  };

  const panelTree = updateTreeNode(layout.panelTree, panelId, (panel) => ({
    type: "group" as const,
    id: generatePanelId(layout.panelTree),
    direction: config.splitDirection,
    sizes: [50, 50],
    children: config.isAfter ? [panel, newPanel] : [newPanel, panel],
  }));

  return { panelTree, focusedPanelId: newPanelId };
}

/**
 * Closes every closeable tab in the pane and collapses its split. Tabs that
 * cannot close (Chat) move to the neighbor pane. The last pane stays, as the
 * last editor group does in VS Code, and only loses its closeable tabs.
 */
export function closePanel(
  layout: TaskLayout,
  panelId: string,
): Partial<TaskLayout> {
  const panel = getLeafPanel(layout.panelTree, panelId);
  if (!panel) return {};

  const closingTabs = panel.content.tabs.filter(
    (tab) => tab.closeable !== false,
  );
  const pinnedTabs = panel.content.tabs.filter(
    (tab) => tab.closeable === false,
  );
  const openFiles = closingTabs.reduce(
    (files, tab) =>
      updateMetadataForTab({ ...layout, openFiles: files }, tab.id, "remove")
        .openFiles,
    layout.openFiles,
  );

  const neighbor = findNeighborLeaf(layout.panelTree, panelId);
  if (!neighbor) {
    if (closingTabs.length === 0) return {};
    const activeTabId = pinnedTabs.some(
      (tab) => tab.id === panel.content.activeTabId,
    )
      ? panel.content.activeTabId
      : (pinnedTabs[0]?.id ?? "");
    const panelTree = updateTreeNode(layout.panelTree, panelId, (node) =>
      node.type !== "leaf"
        ? node
        : {
            ...node,
            content: { ...node.content, tabs: pinnedTabs, activeTabId },
          },
    );
    return { panelTree, openFiles };
  }

  const emptiedTree = updateTreeNode(layout.panelTree, panelId, (node) =>
    node.type !== "leaf"
      ? node
      : { ...node, content: { ...node.content, tabs: [], activeTabId: "" } },
  );
  const treeWithPinnedTabs =
    pinnedTabs.length === 0
      ? emptiedTree
      : updateTreeNode(emptiedTree, neighbor.id, (node) =>
          node.type !== "leaf"
            ? node
            : {
                ...node,
                content: {
                  ...node.content,
                  tabs: [...node.content.tabs, ...pinnedTabs],
                },
              },
        );
  const panelTree = applyCleanupWithFallback(
    cleanupNode(treeWithPinnedTabs),
    layout.panelTree,
  );

  return { panelTree, focusedPanelId: neighbor.id, openFiles };
}

export function updateSizes(
  layout: TaskLayout,
  groupId: string,
  sizes: number[],
): Partial<TaskLayout> {
  const updatedTree = updateTreeNode(layout.panelTree, groupId, (node) => {
    if (node.type !== "group") return node;
    return { ...node, sizes };
  });

  return { panelTree: updatedTree };
}

export function updateTabMetadata(
  layout: TaskLayout,
  tabId: string,
  metadata: Partial<Pick<Tab, "hasUnsavedChanges">>,
): Partial<TaskLayout> {
  const tabLocation = findTabInTree(layout.panelTree, tabId);
  if (!tabLocation) return {};

  const updatedTree = updateTreeNode(
    layout.panelTree,
    tabLocation.panelId,
    (panel) => {
      if (panel.type !== "leaf") return panel;

      const updatedTabs = panel.content.tabs.map((tab) =>
        tab.id === tabId ? { ...tab, ...metadata } : tab,
      );

      return {
        ...panel,
        content: {
          ...panel.content,
          tabs: updatedTabs,
        },
      };
    },
  );

  return { panelTree: updatedTree };
}

export function updateTabLabel(
  layout: TaskLayout,
  tabId: string,
  label: string,
): Partial<TaskLayout> {
  const tabLocation = findTabInTree(layout.panelTree, tabId);
  if (!tabLocation) return {};

  const updatedTree = updateTreeNode(
    layout.panelTree,
    tabLocation.panelId,
    (panel) => {
      if (panel.type !== "leaf") return panel;

      const updatedTabs = panel.content.tabs.map((tab) =>
        tab.id === tabId ? { ...tab, label } : tab,
      );

      return {
        ...panel,
        content: {
          ...panel.content,
          tabs: updatedTabs,
        },
      };
    },
  );

  return { panelTree: updatedTree };
}

export function setActiveTab(
  layout: TaskLayout,
  panelId: string,
  tabId: string,
): Partial<TaskLayout> {
  const updatedTree = updateTreeNode(layout.panelTree, panelId, (panel) => {
    if (panel.type !== "leaf") return panel;
    return {
      ...panel,
      content: { ...panel.content, activeTabId: tabId },
    };
  });

  return { panelTree: updatedTree };
}

export function addTerminalTab(
  layout: TaskLayout,
  panelId: string,
): Partial<TaskLayout> {
  const updatedTree = updateTreeNode(layout.panelTree, panelId, (panel) => {
    if (panel.type !== "leaf") return panel;
    return addTabToPanel(panel, createTerminalTab());
  });

  return { panelTree: updatedTree };
}

export function addActionTab(
  layout: TaskLayout,
  panelId: string,
  action: { actionId: string; command: string; cwd: string; label: string },
): Partial<TaskLayout> {
  const tabId = `action-${action.actionId}`;
  const existingTab = findTabInTree(layout.panelTree, tabId);
  if (existingTab) return {};

  const targetPanel = getLeafPanel(layout.panelTree, panelId);
  if (!targetPanel) return {};

  const updatedTree = updateTreeNode(layout.panelTree, panelId, (panel) => {
    if (panel.type !== "leaf") return panel;

    const newTab: Tab = {
      id: tabId,
      label: action.label,
      data: {
        type: "action",
        actionId: action.actionId,
        command: action.command,
        cwd: action.cwd,
        label: action.label,
      },
      component: null,
      draggable: true,
      closeable: true,
    };

    return {
      ...panel,
      content: {
        ...panel.content,
        tabs: [...panel.content.tabs, newTab],
      },
    };
  });

  return { panelTree: updatedTree };
}
