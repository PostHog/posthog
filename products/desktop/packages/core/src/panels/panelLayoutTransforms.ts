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

export const MAX_RECENT_FILES = 10;

export function createDefaultPanelTree(): PanelNode {
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

export function findNonMainLeafPanel(node: PanelNode): PanelNode | null {
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

  const newPanelId = generatePanelId();
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
      id: generatePanelId(),
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

// Opens a read-only snapshot (channel CONTEXT.md, canvas generation
// instructions, …) as a tab in the right-side split (creating the split if
// needed), mirroring openTabInSplit but carrying the content inline in the
// tab's data instead of deriving it from the tab id. Re-opening the same tab id
// just activates the existing tab.
export function openReadonlyTabInSplit(
  layout: TaskLayout,
  tabId: string,
  label: string,
  data: TabData,
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

  const newPanelId = generatePanelId();
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
      id: generatePanelId(),
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
    const newPanelId = generatePanelId();
    const terminalTabId = `shell-${Date.now()}`;
    const newPanel: PanelNode = {
      type: "leaf",
      id: newPanelId,
      content: {
        id: newPanelId,
        tabs: [
          {
            id: terminalTabId,
            label: "Terminal",
            data: {
              type: "terminal",
              terminalId: terminalTabId,
              cwd: "",
            },
            component: null,
            draggable: true,
            closeable: true,
          },
        ],
        activeTabId: terminalTabId,
        showTabs: true,
        droppable: true,
      },
    };

    const updatedTree = updateTreeNode(
      layout.panelTree,
      targetPanelId,
      (panel) => ({
        type: "group" as const,
        id: generatePanelId(),
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
  const newPanelId = generatePanelId();
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
        id: generatePanelId(),
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
  const tabId = `shell-${Date.now()}`;
  const updatedTree = updateTreeNode(layout.panelTree, panelId, (panel) => {
    if (panel.type !== "leaf") return panel;
    return addTabToPanel(panel, {
      id: tabId,
      label: "Terminal",
      data: { type: "terminal", terminalId: tabId, cwd: "" },
      component: null,
      draggable: true,
      closeable: true,
    });
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
