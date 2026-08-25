import * as core from "@posthog/core/panels/panelStoreHelpers";
import type { TaskLayout } from "./panelLayoutStore";
import type { GroupPanel, LeafPanel, PanelNode, Tab } from "./panelTypes";

export type {
  ParsedTabId,
  SplitConfig,
  TabType,
} from "@posthog/core/panels/panelStoreHelpers";

export const DEFAULT_FALLBACK_TAB = core.DEFAULT_FALLBACK_TAB;

export const createFileTabId = core.createFileTabId;
export const parseTabId = core.parseTabId;
export const createTabLabel = core.createTabLabel;
export const generatePanelId = core.generatePanelId;
export const resetPanelIdCounter = core.resetPanelIdCounter;
export const getSplitConfig = core.getSplitConfig;
export const selectNextTabAfterClose = core.selectNextTabAfterClose;

export const findPanelById = core.findPanelById as (
  node: PanelNode,
  panelId: string,
) => PanelNode | null;

export const getLeafPanel = core.getLeafPanel as (
  tree: PanelNode,
  panelId: string,
) => LeafPanel | null;

export const getGroupPanel = core.getGroupPanel as (
  tree: PanelNode,
  panelId: string,
) => GroupPanel | null;

export const createNewTab = core.createNewTab as (
  tabId: string,
  closeable?: boolean,
  isPreview?: boolean,
) => Tab;

export const addNewTabToPanel = core.addNewTabToPanel as (
  panel: PanelNode,
  tabId: string,
  closeable?: boolean,
  isPreview?: boolean,
) => PanelNode;

export const updateMetadataForTab = core.updateMetadataForTab as (
  layout: TaskLayout,
  tabId: string,
  action: "add" | "remove",
) => Pick<TaskLayout, "openFiles">;

export const applyCleanupWithFallback = core.applyCleanupWithFallback as (
  cleanedTree: PanelNode | null,
  originalTree: PanelNode,
) => PanelNode;

export const isTabActiveInTree = core.isTabActiveInTree as (
  tree: PanelNode,
  tabId: string,
) => boolean;

export const isFileTabActiveInTree = core.isFileTabActiveInTree as (
  tree: PanelNode,
  filePath: string,
) => boolean;

export function updateTaskLayout(
  state: { taskLayouts: Record<string, TaskLayout> },
  taskId: string,
  updater: (layout: TaskLayout) => Partial<TaskLayout>,
): { taskLayouts: Record<string, TaskLayout> } {
  const layout = state.taskLayouts[taskId];
  if (!layout) return state;

  const updates = updater(layout);

  return {
    taskLayouts: {
      ...state.taskLayouts,
      [taskId]: {
        ...layout,
        ...updates,
      },
    },
  };
}
