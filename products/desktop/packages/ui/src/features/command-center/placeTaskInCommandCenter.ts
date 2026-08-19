import {
  type ExpandDirection,
  getExpandedLayout,
  getExpansionCellIndex,
} from "@posthog/core/command-center/grid";
import { planCommandCenterPlacement } from "@posthog/core/command-center/placement";
import { navigateToCommandCenter } from "@posthog/ui/router/navigationBridge";
import { useCommandCenterStore } from "./commandCenterStore";

/**
 * Opens the command center with the tile picker up. Adding always asks, even
 * with tiles free: guessing a tile means the task lands somewhere the user
 * wasn't looking, and picking is one click either way.
 */
export function placeTaskInCommandCenter(
  taskId: string,
  taskTitle: string,
): void {
  useCommandCenterStore.getState().requestPlacement(taskId, taskTitle);
  navigateToCommandCenter();
}

export interface BulkPlacementResult {
  placed: number;
  overflow: number;
  alreadyPresent: number;
}

/**
 * Tiles a whole selection at once. Unlike the single-task flow there is no
 * picker — asking for a slot per session doesn't scale — so it navigates to the
 * grid instead, where a batch that had to grow the layout is self-evident.
 */
export function placeTasksInCommandCenter(
  taskIds: string[],
  liveTaskIds: ReadonlySet<string> | null,
): BulkPlacementResult {
  const state = useCommandCenterStore.getState();
  const plan = planCommandCenterPlacement({
    cells: state.cells,
    layout: state.layout,
    taskIds,
    liveTaskIds,
  });

  if (plan.placed.length > 0) {
    state.applyPlacement({ layout: plan.layout, cells: plan.cells });
  }
  navigateToCommandCenter();

  return {
    placed: plan.placed.length,
    overflow: plan.overflow.length,
    alreadyPresent: plan.alreadyPresent.length,
  };
}

export function placeTasksInCommandCenterCell(
  taskIds: string[],
  cellIndex: number,
): void {
  const [firstTaskId, ...remainingTaskIds] = taskIds;
  if (!firstTaskId) return;

  useCommandCenterStore.getState().assignTask(cellIndex, firstTaskId);
  if (remainingTaskIds.length > 0) {
    placeTasksInCommandCenter(remainingTaskIds, null);
  }
}

export function expandTasksInCommandCenterInto(
  direction: ExpandDirection,
  slot: number,
  taskIds: string[],
): void {
  const [firstTaskId, ...remainingTaskIds] = taskIds;
  if (!firstTaskId) return;

  const state = useCommandCenterStore.getState();
  const expanded = getExpandedLayout(state.layout, direction);
  if (!expanded) return;

  state.setLayout(expanded);
  useCommandCenterStore
    .getState()
    .assignTask(getExpansionCellIndex(expanded, direction, slot), firstTaskId);
  if (remainingTaskIds.length > 0) {
    placeTasksInCommandCenter(remainingTaskIds, null);
  }
}
