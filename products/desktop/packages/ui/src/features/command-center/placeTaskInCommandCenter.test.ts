import { makeCanvasCellValue } from "@posthog/core/command-center/grid";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  COMMAND_CENTER_INITIAL_STATE,
  useCommandCenterStore,
} from "./commandCenterStore";
import {
  placeCanvasInCommandCenter,
  placeCanvasInCommandCenterCell,
  placeTasksInCommandCenterCell,
} from "./placeTaskInCommandCenter";

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToCommandCenter: vi.fn(),
}));

describe("canvas placement", () => {
  beforeEach(() => {
    useCommandCenterStore.setState(COMMAND_CENTER_INITIAL_STATE);
  });

  it("opens the tile picker for a canvas", () => {
    placeCanvasInCommandCenter("canvas-1", "Activation overview");

    expect(useCommandCenterStore.getState().pendingPlacement).toEqual({
      kind: "canvas",
      id: "canvas-1",
      title: "Activation overview",
    });
  });

  it("places a canvas in the selected cell", () => {
    placeCanvasInCommandCenterCell("canvas-1", 1);

    expect(useCommandCenterStore.getState().cells[1]).toBe(
      makeCanvasCellValue("canvas-1"),
    );
  });
});

describe("placeTasksInCommandCenterCell", () => {
  beforeEach(() => {
    useCommandCenterStore.setState({
      ...COMMAND_CENTER_INITIAL_STATE,
      cells: ["existing", null, null, null],
    });
  });

  // The grabbed task is written into the drop target first, then the rest are
  // placed around it. A live set that predates the grabbed task (unknown, or
  // scoped so it never listed it) must not let that second pass tile over it.
  const liveSets: Array<[string, ReadonlySet<string> | null]> = [
    ["an unknown live set", null],
    [
      "a live set missing the grabbed task",
      new Set(["existing", "selected-2", "selected-3"]),
    ],
  ];

  it.each(liveSets)(
    "keeps the grabbed task in the drop target with %s",
    (_label, liveTaskIds) => {
      placeTasksInCommandCenterCell(
        ["dragged", "selected-2", "selected-3"],
        0,
        liveTaskIds,
      );

      expect(useCommandCenterStore.getState().cells).toEqual([
        "dragged",
        "selected-2",
        "selected-3",
        null,
      ]);
    },
  );
});
