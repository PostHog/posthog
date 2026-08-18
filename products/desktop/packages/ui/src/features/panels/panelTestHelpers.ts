import { usePanelLayoutStore } from "./panelLayoutStore";
import type { PanelNode } from "./panelTypes";

export function findPanelById(
  node: PanelNode,
  panelId: string,
): Extract<PanelNode, { type: "leaf" }> | null {
  if (node.id === panelId && node.type === "leaf") {
    return node;
  }

  if (node.type === "group") {
    for (const child of node.children) {
      const found = findPanelById(child, panelId);
      if (found) return found;
    }
  }

  return null;
}

export interface ExpectedPanelLayout {
  panelId: string;
  expectedTabs: string[];
  activeTab?: string;
}

export function assertPanelLayout(
  tree: PanelNode,
  expectations: ExpectedPanelLayout[],
) {
  for (const { panelId, expectedTabs, activeTab } of expectations) {
    const panel = findPanelById(tree, panelId);
    if (!panel) {
      throw new Error(`Panel ${panelId} not found in tree`);
    }

    const actualTabs = panel.content.tabs.map((t) => t.id);

    if (actualTabs.length !== expectedTabs.length) {
      throw new Error(
        `Panel ${panelId}: expected ${expectedTabs.length} tabs but got ${actualTabs.length}. Expected: [${expectedTabs.join(", ")}], Got: [${actualTabs.join(", ")}]`,
      );
    }

    for (const expectedTab of expectedTabs) {
      if (!actualTabs.includes(expectedTab)) {
        throw new Error(
          `Panel ${panelId}: expected tab "${expectedTab}" but it was not found. Got: [${actualTabs.join(", ")}]`,
        );
      }
    }

    if (activeTab && panel.content.activeTabId !== activeTab) {
      throw new Error(
        `Panel ${panelId}: expected active tab "${activeTab}" but got "${panel.content.activeTabId}"`,
      );
    }
  }
}

export function assertActiveTab(
  tree: PanelNode,
  panelId: string,
  expectedTabId: string,
) {
  const panel = findPanelById(tree, panelId);
  if (!panel) {
    throw new Error(`Panel ${panelId} not found in tree`);
  }

  if (panel.content.activeTabId !== expectedTabId) {
    throw new Error(
      `Panel ${panelId}: expected active tab "${expectedTabId}" but got "${panel.content.activeTabId}"`,
    );
  }
}

export function assertTabCount(
  tree: PanelNode,
  panelId: string,
  expectedCount: number,
) {
  const panel = findPanelById(tree, panelId);
  if (!panel) {
    throw new Error(`Panel ${panelId} not found in tree`);
  }

  if (panel.content.tabs.length !== expectedCount) {
    const actualTabs = panel.content.tabs.map((t) => t.id).join(", ");
    throw new Error(
      `Panel ${panelId}: expected ${expectedCount} tabs but got ${panel.content.tabs.length}. Actual: [${actualTabs}]`,
    );
  }
}

export function openMultipleFiles(taskId: string, files: string[]) {
  for (const file of files) {
    usePanelLayoutStore.getState().openFile(taskId, file, false);
  }
}

export type GroupNode = Extract<PanelNode, { type: "group" }>;

export function withRootGroup(
  taskId: string,
  callback: (root: GroupNode) => void,
) {
  const layout = usePanelLayoutStore.getState().getLayout(taskId);
  const root = layout?.panelTree;

  if (!root) {
    throw new Error(`No layout found for task ${taskId}`);
  }

  if (root.type !== "group") {
    throw new Error(
      `Expected group node for task ${taskId} but got ${root.type} (id: ${root.id})`,
    );
  }

  callback(root);
}

export function getLayout(taskId: string) {
  const layout = usePanelLayoutStore.getState().getLayout(taskId);
  if (!layout) {
    throw new Error(`No layout found for task ${taskId}`);
  }
  return layout;
}

export function getPanelTree(taskId: string) {
  return getLayout(taskId).panelTree;
}
