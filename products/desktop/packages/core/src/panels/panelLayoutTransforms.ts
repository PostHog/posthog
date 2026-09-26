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
  collectLeafPanels,
  findNeighborLeaf,
  findTabInPanel,
  findTabInTree,
  removeTabFromPanel,
  updateTreeNode,
} from "./panelTree";
import type {
  LeafPanel,
  PanelContent,
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

function splitWithNewPanel(
  tree: PanelNode,
  targetPanelId: string,
  tab: Tab,
  direction: SplitDirection,
): { panelTree: PanelNode; newPanelId: string } {
  const config = getSplitConfig(direction);
  const newPanelId = generatePanelId(tree);
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

  const panelTree = updateTreeNode(tree, targetPanelId, (panel) => ({
    type: "group" as const,
    id: generatePanelId(tree),
    direction: config.splitDirection,
    sizes: [50, 50],
    children: config.isAfter ? [panel, newPanel] : [newPanel, panel],
  }));

  return { panelTree, newPanelId };
}

function updateLeafContent(
  tree: PanelNode,
  panelId: string,
  update: (content: PanelContent) => Partial<PanelContent>,
): PanelNode {
  return updateTreeNode(tree, panelId, (node) =>
    node.type === "leaf"
      ? { ...node, content: { ...node.content, ...update(node.content) } }
      : node,
  );
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

function findNonMainLeafPanel(node: PanelNode): LeafPanel | null {
  return (
    collectLeafPanels(node).find(
      (leaf) => leaf.id !== DEFAULT_PANEL_IDS.MAIN_PANEL,
    ) ?? null
  );
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

  const { panelTree, newPanelId } = splitWithNewPanel(
    layout.panelTree,
    DEFAULT_PANEL_IDS.MAIN_PANEL,
    buildTab(),
    "right",
  );
  return { panelTree, focusedPanelId: newPanelId };
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

  return {
    panelTree: cleanedTree,
    openFiles: pruneOpenFiles(layout.openFiles, cleanedTree),
  };
}

// Copied file tabs have their own ids, so match open files by path.
function pruneOpenFiles(openFiles: string[], tree: PanelNode): string[] {
  const openPaths = new Set(
    collectLeafPanels(tree).flatMap((leaf) =>
      leaf.content.tabs.flatMap((tab) =>
        tab.data.type === "file" ? [tab.data.relativePath] : [],
      ),
    ),
  );
  return openFiles.filter((file) => openPaths.has(file));
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
    const { panelTree, newPanelId } = splitWithNewPanel(
      layout.panelTree,
      targetPanelId,
      createTerminalTab(),
      direction,
    );
    return { panelTree, focusedPanelId: newPanelId };
  }

  const treeAfterRemove = updateTreeNode(
    layout.panelTree,
    sourcePanelId,
    (panel) => removeTabFromPanel(panel, tabId),
  );

  const { panelTree: updatedTree } = splitWithNewPanel(
    treeAfterRemove,
    targetPanelId,
    tab,
    direction,
  );

  const cleanedTree = applyCleanupWithFallback(
    cleanupNode(updatedTree),
    layout.panelTree,
  );

  return { panelTree: cleanedTree };
}

const COPY_TAB_ID_PATTERN = /^copy-\d+:(.*)$/;

// Tab ids key React lists and tab lookups, so a copy needs its own id. The
// "copy-" prefix keeps it out of the file-tab id parsing.
function createCopyTabId(tree: PanelNode, sourceTabId: string): string {
  const baseId = sourceTabId.match(COPY_TAB_ID_PATTERN)?.[1] ?? sourceTabId;
  let copyNumber = 2;
  while (findTabInTree(tree, `copy-${copyNumber}:${baseId}`)) {
    copyNumber++;
  }
  return `copy-${copyNumber}:${baseId}`;
}

function copyTab(tree: PanelNode, tab: Tab): Tab {
  // Two views of one pty would fight over its input, so open a fresh shell.
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

/** VS Code "Split editor": the new pane shows a copy of the active tab. */
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

  const { panelTree, newPanelId } = splitWithNewPanel(
    layout.panelTree,
    panelId,
    copyTab(layout.panelTree, activeTab),
    direction,
  );
  return { panelTree, focusedPanelId: newPanelId };
}

export function closePanel(
  layout: TaskLayout,
  panelId: string,
): Partial<TaskLayout> {
  const panel = getLeafPanel(layout.panelTree, panelId);
  if (!panel) return {};

  const pinnedTabs = panel.content.tabs.filter(
    (tab) => tab.closeable === false,
  );
  const neighbor = findNeighborLeaf(layout.panelTree, panelId);

  if (!neighbor) {
    // The last pane has nowhere to send its pinned tabs, so it keeps them.
    if (pinnedTabs.length === panel.content.tabs.length) return {};
    const panelTree = updateLeafContent(
      layout.panelTree,
      panelId,
      ({ activeTabId }) => ({
        tabs: pinnedTabs,
        activeTabId:
          pinnedTabs.find((tab) => tab.id === activeTabId)?.id ??
          pinnedTabs[0]?.id ??
          "",
      }),
    );
    return {
      panelTree,
      openFiles: pruneOpenFiles(layout.openFiles, panelTree),
    };
  }

  const movedTree = updateLeafContent(
    updateLeafContent(layout.panelTree, panelId, () => ({ tabs: [] })),
    neighbor.id,
    ({ tabs }) => ({ tabs: [...tabs, ...pinnedTabs] }),
  );
  const panelTree = applyCleanupWithFallback(
    cleanupNode(movedTree),
    layout.panelTree,
  );

  return {
    panelTree,
    focusedPanelId: neighbor.id,
    openFiles: pruneOpenFiles(layout.openFiles, panelTree),
  };
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
