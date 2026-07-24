import { DEFAULT_TAB_IDS } from "./panelConstants";
import type {
  GroupPanel,
  LeafPanel,
  PanelNode,
  SplitDirection,
  Tab,
  TaskLayout,
} from "./panelTypes";

export const DEFAULT_FALLBACK_TAB = DEFAULT_TAB_IDS.LOGS;

export type TabType = "file" | "system";

export interface ParsedTabId {
  type: TabType;
  value: string;
}

export function createFileTabId(filePath: string): string {
  return `file-${filePath}`;
}

export function parseTabId(tabId: string): ParsedTabId & { status?: string } {
  if (tabId.startsWith("file-")) {
    return { type: "file", value: tabId.slice(5) };
  }
  return { type: "system", value: tabId };
}

export function createTabLabel(tabId: string): string {
  const parsed = parseTabId(tabId);
  if (parsed.type === "file") {
    return parsed.value.split("/").pop() || parsed.value;
  }
  return parsed.value;
}

export function findPanelById(
  node: PanelNode,
  panelId: string,
): PanelNode | null {
  if (node.id === panelId) {
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

export function getLeafPanel(
  tree: PanelNode,
  panelId: string,
): LeafPanel | null {
  const panel = findPanelById(tree, panelId);
  return panel?.type === "leaf" ? panel : null;
}

export function getGroupPanel(
  tree: PanelNode,
  panelId: string,
): GroupPanel | null {
  const panel = findPanelById(tree, panelId);
  return panel?.type === "group" ? panel : null;
}

let nextPanelId = 1;

export function generatePanelId(): string {
  return `panel-${nextPanelId++}`;
}

export function resetPanelIdCounter(): void {
  nextPanelId = 1;
}

export function createNewTab(
  tabId: string,
  closeable = true,
  isPreview = false,
): Tab {
  const parsed = parseTabId(tabId);
  let data: Tab["data"];

  switch (parsed.type) {
    case "file":
      data = {
        type: "file",
        relativePath: parsed.value,
        absolutePath: "",
        repoPath: "",
      };
      break;
    case "system":
      if (tabId === "logs") {
        data = { type: "logs" };
      } else if (tabId.startsWith("shell")) {
        data = {
          type: "terminal",
          terminalId: tabId,
          cwd: "",
        };
      } else {
        data = { type: "other" };
      }
      break;
    default:
      data = { type: "other" };
  }

  return {
    id: tabId,
    label: createTabLabel(tabId),
    data,
    component: null,
    closeable,
    draggable: true,
    isPreview,
  };
}

export function addNewTabToPanel(
  panel: PanelNode,
  tabId: string,
  closeable = true,
  isPreview = false,
): PanelNode {
  if (panel.type !== "leaf") return panel;

  const tabs = isPreview
    ? panel.content.tabs.filter((tab) => !tab.isPreview)
    : panel.content.tabs;

  return {
    ...panel,
    content: {
      ...panel.content,
      tabs: [...tabs, createNewTab(tabId, closeable, isPreview)],
      activeTabId: tabId,
    },
  };
}

export function selectNextTabAfterClose(
  tabs: Tab[],
  closedTabIndex: number,
  activeTabId: string,
  closedTabId: string,
): string {
  if (activeTabId !== closedTabId) {
    return activeTabId;
  }

  if (tabs.length === 0) {
    return DEFAULT_FALLBACK_TAB;
  }

  const nextIndex = Math.min(closedTabIndex, tabs.length - 1);
  return tabs[nextIndex].id;
}

export interface SplitConfig {
  splitDirection: "horizontal" | "vertical";
  isAfter: boolean;
}

export function getSplitConfig(direction: SplitDirection): SplitConfig {
  const horizontalDirections: SplitDirection[] = ["left", "right"];
  const afterDirections: SplitDirection[] = ["right", "bottom"];

  return {
    splitDirection: horizontalDirections.includes(direction)
      ? "horizontal"
      : "vertical",
    isAfter: afterDirections.includes(direction),
  };
}

export function updateMetadataForTab(
  layout: TaskLayout,
  tabId: string,
  action: "add" | "remove",
): Pick<TaskLayout, "openFiles"> {
  const parsed = parseTabId(tabId);

  if (parsed.type === "file") {
    const openFiles =
      action === "add"
        ? [...layout.openFiles, parsed.value]
        : layout.openFiles.filter((f) => f !== parsed.value);
    return { openFiles };
  }

  return { openFiles: layout.openFiles };
}

export function applyCleanupWithFallback(
  cleanedTree: PanelNode | null,
  originalTree: PanelNode,
): PanelNode {
  return cleanedTree || originalTree;
}

export function isTabActiveInTree(tree: PanelNode, tabId: string): boolean {
  if (tree.type === "leaf") {
    return tree.content.activeTabId === tabId;
  }
  return tree.children.some((child) => isTabActiveInTree(child, tabId));
}

export function isFileTabActiveInTree(
  tree: PanelNode,
  filePath: string,
): boolean {
  const tabId = createFileTabId(filePath);
  return isTabActiveInTree(tree, tabId);
}
