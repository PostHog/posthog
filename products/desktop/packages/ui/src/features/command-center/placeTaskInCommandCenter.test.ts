import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  COMMAND_CENTER_INITIAL_STATE,
  useCommandCenterStore,
} from "./commandCenterStore";
import { placeTasksInCommandCenterCell } from "./placeTaskInCommandCenter";

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToCommandCenter: vi.fn(),
}));

describe("placeTasksInCommandCenterCell", () => {
  beforeEach(() => {
    useCommandCenterStore.setState({
      ...COMMAND_CENTER_INITIAL_STATE,
      cells: ["existing", null, null, null],
    });
  });

  it("places the grabbed task in the drop target and the rest in available cells", () => {
    placeTasksInCommandCenterCell(["dragged", "selected-2", "selected-3"], 0);

    expect(useCommandCenterStore.getState().cells).toEqual([
      "dragged",
      "selected-2",
      "selected-3",
      null,
    ]);
  });
});
