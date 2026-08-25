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
  useCommandCenterStore.getState().requestPlacement({
    kind: "task",
    id: taskId,
    title: taskTitle,
  });
  navigateToCommandCenter();
}

export function placeCanvasInCommandCenter(
  canvasId: string,
  canvasTitle: string,
): void {
  useCommandCenterStore.getState().requestPlacement({
    kind: "canvas",
    id: canvasId,
    title: canvasTitle,
  });
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

/**
 * The live set widened to cover a task just written into a tile. A `null` set
 * already holds every filled tile, so the assigned task is safe there; a known
 * set can lag behind a task created elsewhere, and without the id the batch
 * would tile over the very cell it was just placed in.
 */
function withAssignedTask(
  liveTaskIds: ReadonlySet<string> | null,
  taskId: string,
): ReadonlySet<string> | null {
  return liveTaskIds == null ? null : new Set([...liveTaskIds, taskId]);
}

export function placeTasksInCommandCenterCell(
  taskIds: string[],
  cellIndex: number,
  liveTaskIds: ReadonlySet<string> | null,
): void {
  const [firstTaskId, ...remainingTaskIds] = taskIds;
  if (!firstTaskId) return;

  useCommandCenterStore.getState().assignTask(cellIndex, firstTaskId);
  if (remainingTaskIds.length > 0) {
    placeTasksInCommandCenter(
      remainingTaskIds,
      withAssignedTask(liveTaskIds, firstTaskId),
    );
  }
}

export function placeCanvasInCommandCenterCell(
  canvasId: string,
  cellIndex: number,
): void {
  useCommandCenterStore.getState().setCanvasCell(cellIndex, canvasId);
}

export function expandCanvasInCommandCenterInto(
  direction: ExpandDirection,
  slot: number,
  canvasId: string,
): void {
  const state = useCommandCenterStore.getState();
  const expanded = getExpandedLayout(state.layout, direction);
  if (!expanded) return;

  state.setLayout(expanded);
  useCommandCenterStore
    .getState()
    .setCanvasCell(getExpansionCellIndex(expanded, direction, slot), canvasId);
}

export function expandTasksInCommandCenterInto(
  direction: ExpandDirection,
  slot: number,
  taskIds: string[],
  liveTaskIds: ReadonlySet<string> | null,
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
    placeTasksInCommandCenter(
      remainingTaskIds,
      withAssignedTask(liveTaskIds, firstTaskId),
    );
  }
}
