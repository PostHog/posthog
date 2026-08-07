import { findCommandCenterPlacement } from "@posthog/core/command-center/grid";
import { navigateToCommandCenter } from "@posthog/ui/router/navigationBridge";
import { useCommandCenterStore } from "./commandCenterStore";

export function placeTaskInCommandCenter(
  taskId: string,
  taskTitle: string,
  liveTaskIds: ReadonlySet<string>,
): void {
  const state = useCommandCenterStore.getState();
  const placement = findCommandCenterPlacement(
    state.cells,
    state.layout,
    liveTaskIds,
  );

  if (placement) {
    if (placement.layout !== state.layout) state.setLayout(placement.layout);
    useCommandCenterStore.getState().assignTask(placement.cellIndex, taskId);
  } else {
    state.requestPlacement(taskId, taskTitle);
  }
  navigateToCommandCenter();
}
