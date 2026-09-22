import * as core from "@posthog/core/panels/panelStoreHelpers";
import type { TaskLayout } from "./panelLayoutStore";
import type { LeafPanel, PanelNode } from "./panelTypes";

export const findPanelById = core.findPanelById as (
  node: PanelNode,
  panelId: string,
) => PanelNode | null;

export const getLeafPanel = core.getLeafPanel as (
  tree: PanelNode,
  panelId: string,
) => LeafPanel | null;

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
