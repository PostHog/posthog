import {
  BRAINROT_CELL,
  makeCanvasCellValue,
  makeTerminalCellValue,
} from "@posthog/core/command-center/grid";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/rendererStorage", () => ({
  electronStorage: {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  },
}));

import {
  COMMAND_CENTER_INITIAL_STATE,
  useCommandCenterStore,
} from "./commandCenterStore";

function resetStore() {
  useCommandCenterStore.setState(COMMAND_CENTER_INITIAL_STATE);
}

describe("commandCenterStore", () => {
  beforeEach(resetStore);

  describe("autofillCells", () => {
    it.each([
      {
        name: "fills empty cells from index 0",
        input: ["t1", "t2"],
        expectedCells: ["t1", "t2", null, null],
      },
      {
        name: "ignores empty task list",
        input: [],
        expectedCells: [null, null, null, null],
      },
      {
        name: "caps fill at the number of cells",
        input: ["t1", "t2", "t3", "t4", "t5", "t6"],
        expectedCells: ["t1", "t2", "t3", "t4"],
      },
    ])("$name and leaves activeTaskId null", ({ input, expectedCells }) => {
      useCommandCenterStore.getState().autofillCells(input);
      expect(useCommandCenterStore.getState().cells).toEqual(expectedCells);
      expect(useCommandCenterStore.getState().activeTaskId).toBeNull();
    });

    it("fills only the empty slots when some cells are already populated", () => {
      useCommandCenterStore.setState({ cells: [null, "existing", null, null] });
      useCommandCenterStore.getState().autofillCells(["t1", "t2", "t3"]);
      expect(useCommandCenterStore.getState().cells).toEqual([
        "t1",
        "existing",
        "t2",
        "t3",
      ]);
    });

    it("does nothing when every cell is already populated", () => {
      useCommandCenterStore.setState({ cells: ["a", "b", "c", "d"] });
      useCommandCenterStore.getState().autofillCells(["t1", "t2"]);
      expect(useCommandCenterStore.getState().cells).toEqual([
        "a",
        "b",
        "c",
        "d",
      ]);
    });

    it("stops filling when task list runs out before empty slots do", () => {
      useCommandCenterStore.setState({ cells: [null, null, "x", null] });
      useCommandCenterStore.getState().autofillCells(["t1"]);
      expect(useCommandCenterStore.getState().cells).toEqual([
        "t1",
        null,
        "x",
        null,
      ]);
    });

    it("sets hasAutofilled when it populates cells", () => {
      useCommandCenterStore.getState().autofillCells(["t1"]);
      expect(useCommandCenterStore.getState().hasAutofilled).toBe(true);
    });

    it("leaves hasAutofilled unset when there is nothing to fill", () => {
      useCommandCenterStore.getState().autofillCells([]);
      expect(useCommandCenterStore.getState().hasAutofilled).toBe(false);
    });
  });

  describe("setBrainrotCell", () => {
    it("marks the target cell as brainrot without disturbing others", () => {
      useCommandCenterStore.setState({ cells: ["t1", null, null, null] });
      useCommandCenterStore.getState().setBrainrotCell(2);
      expect(useCommandCenterStore.getState().cells).toEqual([
        "t1",
        null,
        BRAINROT_CELL,
        null,
      ]);
    });

    it("does not dedupe, so multiple cells can be brainrot", () => {
      useCommandCenterStore.getState().setBrainrotCell(0);
      useCommandCenterStore.getState().setBrainrotCell(1);
      expect(useCommandCenterStore.getState().cells).toEqual([
        BRAINROT_CELL,
        BRAINROT_CELL,
        null,
        null,
      ]);
    });

    it("focuses the cell, clears its creating state, and marks the grid curated", () => {
      useCommandCenterStore.setState({ creatingCells: [3] });
      useCommandCenterStore.getState().setBrainrotCell(3);
      const state = useCommandCenterStore.getState();
      expect(state.activeCellIndex).toBe(3);
      expect(state.activeTaskId).toBeNull();
      expect(state.creatingCells).toEqual([]);
      expect(state.hasAutofilled).toBe(true);
    });

    it("ignores out-of-range indices", () => {
      useCommandCenterStore.getState().setBrainrotCell(9);
      expect(useCommandCenterStore.getState().cells).toEqual([
        null,
        null,
        null,
        null,
      ]);
    });
  });

  describe("setTerminalCell", () => {
    it("stores the terminal cell value without disturbing others", () => {
      useCommandCenterStore.setState({ cells: ["t1", null, null, null] });
      useCommandCenterStore.getState().setTerminalCell(2, "term-1");
      expect(useCommandCenterStore.getState().cells).toEqual([
        "t1",
        null,
        makeTerminalCellValue("term-1"),
        null,
      ]);
    });

    it("focuses the cell, clears its creating state, and marks the grid curated", () => {
      useCommandCenterStore.setState({ creatingCells: [3] });
      useCommandCenterStore.getState().setTerminalCell(3, "term-1");
      const state = useCommandCenterStore.getState();
      expect(state.activeCellIndex).toBe(3);
      expect(state.activeTaskId).toBeNull();
      expect(state.creatingCells).toEqual([]);
      expect(state.hasAutofilled).toBe(true);
    });

    it("ignores out-of-range indices", () => {
      useCommandCenterStore.getState().setTerminalCell(9, "term-1");
      expect(useCommandCenterStore.getState().cells).toEqual([
        null,
        null,
        null,
        null,
      ]);
    });
  });

  describe("setCanvasCell", () => {
    it("stores one canvas once and focuses its cell", () => {
      useCommandCenterStore.getState().setCanvasCell(1, "canvas-1");
      useCommandCenterStore.getState().setCanvasCell(3, "canvas-1");

      const state = useCommandCenterStore.getState();
      expect(state.cells).toEqual([
        null,
        null,
        null,
        makeCanvasCellValue("canvas-1"),
      ]);
      expect(state.activeCellIndex).toBe(3);
      expect(state.activeTaskId).toBeNull();
      expect(state.hasAutofilled).toBe(true);
    });

    it("clears a pending canvas placement", () => {
      useCommandCenterStore.getState().requestPlacement({
        kind: "canvas",
        id: "canvas-1",
        title: "Activation overview",
      });
      useCommandCenterStore.getState().setCanvasCell(2, "canvas-1");

      expect(useCommandCenterStore.getState().pendingPlacement).toBeNull();
    });
  });

  describe("hasAutofilled", () => {
    it("assigning a task marks the grid as curated", () => {
      useCommandCenterStore.getState().assignTask(0, "t1");
      expect(useCommandCenterStore.getState().hasAutofilled).toBe(true);
    });

    it("marks the grid as autofilled when it is already full", () => {
      useCommandCenterStore.setState({ cells: ["a", "b", "c", "d"] });
      useCommandCenterStore.getState().autofillCells([]);
      expect(useCommandCenterStore.getState().hasAutofilled).toBe(true);
    });
  });

  // The write every bulk placement lands through. The plan itself is covered by
  // placement.test.ts; what's here is the reconciliation only this write does.
  describe("applyPlacement", () => {
    it("follows the active task to its new index when the grid grows", () => {
      useCommandCenterStore.setState({
        layout: "2x2",
        cells: ["a", "b", "c", null],
        activeTaskId: "c",
        activeCellIndex: 2,
      });

      useCommandCenterStore.getState().applyPlacement({
        layout: "3x2",
        cells: ["a", "b", "d", "c", "e", "f"],
      });

      const state = useCommandCenterStore.getState();
      expect(state.layout).toBe("3x2");
      expect(state.activeTaskId).toBe("c");
      expect(state.activeCellIndex).toBe(3);
    });

    it("drops the active task when the placement left it off the grid", () => {
      useCommandCenterStore.setState({
        cells: ["a", null, null, null],
        activeTaskId: "a",
        activeCellIndex: 0,
      });

      useCommandCenterStore
        .getState()
        .applyPlacement({ layout: "2x2", cells: ["b", null, null, null] });

      const state = useCommandCenterStore.getState();
      expect(state.activeTaskId).toBeNull();
      expect(state.activeCellIndex).toBe(0);
    });

    // Otherwise a "creating" spinner sits on a tile that now holds a session.
    it("stops marking a filled cell as creating", () => {
      useCommandCenterStore.setState({
        cells: [null, null, null, null],
        creatingCells: [1, 2],
      });

      useCommandCenterStore
        .getState()
        .applyPlacement({ layout: "2x2", cells: [null, "a", null, null] });

      expect(useCommandCenterStore.getState().creatingCells).toEqual([2]);
    });

    it("marks the grid curated so autofill can't stuff it later", () => {
      useCommandCenterStore
        .getState()
        .applyPlacement({ layout: "2x2", cells: ["a", null, null, null] });

      expect(useCommandCenterStore.getState().hasAutofilled).toBe(true);
    });
  });

  describe("pending placement", () => {
    it("keeps the requested task available until placement is canceled", () => {
      useCommandCenterStore.getState().requestPlacement({
        kind: "task",
        id: "t1",
        title: "Fix signup",
      });
      expect(useCommandCenterStore.getState().pendingPlacement).toEqual({
        kind: "task",
        id: "t1",
        title: "Fix signup",
      });

      useCommandCenterStore.getState().cancelPlacement();
      expect(useCommandCenterStore.getState().pendingPlacement).toBeNull();
    });

    it("clears the request when the task is assigned", () => {
      useCommandCenterStore.getState().requestPlacement({
        kind: "task",
        id: "t1",
        title: "Fix signup",
      });
      useCommandCenterStore.getState().assignTask(2, "t1");
      expect(useCommandCenterStore.getState().pendingPlacement).toBeNull();
      expect(useCommandCenterStore.getState().cells[2]).toBe("t1");
    });
  });
});
