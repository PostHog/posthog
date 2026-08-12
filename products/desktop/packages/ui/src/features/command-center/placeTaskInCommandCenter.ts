import {
  type ExpandDirection,
  getExpandedLayout,
  getExpansionCellIndex,
} from "@posthog/core/command-center/grid";
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

/** Grows the grid by one column or row and puts the task in the slot picked. */
export function expandCommandCenterInto(
  direction: ExpandDirection,
  slot: number,
  taskId: string,
): void {
  const state = useCommandCenterStore.getState();
  const expanded = getExpandedLayout(state.layout, direction);
  if (!expanded) return;

  state.setLayout(expanded);
  useCommandCenterStore
    .getState()
    .assignTask(getExpansionCellIndex(expanded, direction, slot), taskId);
}
