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

const store = () => useCommandCenterStore.getState();

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

    it("focuses the cell and marks the grid curated", () => {
      useCommandCenterStore.getState().setBrainrotCell(3);
      const state = useCommandCenterStore.getState();
      expect(state.activeCellIndex).toBe(3);
      expect(state.activeTaskId).toBeNull();
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

    it("focuses the cell and marks the grid curated", () => {
      useCommandCenterStore.getState().setTerminalCell(3, "term-1");
      const state = useCommandCenterStore.getState();
      expect(state.activeCellIndex).toBe(3);
      expect(state.activeTaskId).toBeNull();
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

  describe("in-tile composer", () => {
    it("keeps the first active composer and marks the grid curated", () => {
      store().startCreating(2, "session-2");
      store().startCreating(1, "session-1");

      expect(store().composer).toEqual({
        cellIndex: 2,
        sessionId: "session-2",
      });
      expect(store().activeCellIndex).toBe(2);
      expect(store().hasAutofilled).toBe(true);

      store().stopCreating("session-2");
      expect(store().composer).toBeNull();
    });

    it("reserves the composing tile from late autofill", () => {
      store().startCreating(1, "session-1");

      store().autofillCells(["t1", "t2", "t3"]);

      expect(store().cells).toEqual(["t1", null, "t2", "t3"]);
      expect(store().composer).toEqual({
        cellIndex: 1,
        sessionId: "session-1",
      });
    });

    it.each([
      { what: "a task", fill: () => store().assignTask(1, "t1") },
      { what: "a terminal", fill: () => store().setTerminalCell(1, "term-1") },
      { what: "brainrot", fill: () => store().setBrainrotCell(1) },
      { what: "a canvas", fill: () => store().setCanvasCell(1, "canvas-1") },
    ])("does not replace the composer with $what", ({ fill }) => {
      store().startCreating(1, "session-1");

      fill();

      expect(store().cells[1]).toBeNull();
      expect(store().composer).toEqual({
        cellIndex: 1,
        sessionId: "session-1",
      });
    });

    it("keeps the layout stable while composing", () => {
      useCommandCenterStore.setState({
        layout: "2x2",
        cells: [null, "t1", null, null],
      });
      store().startCreating(0, "session-0");

      store().setLayout("3x2", [null, "t1", null, null, null, null]);
      store().optimizeLayout([1]);

      expect(store().layout).toBe("2x2");
      expect(store().cells).toEqual([null, "t1", null, null]);
      expect(store().composer).toEqual({
        cellIndex: 0,
        sessionId: "session-0",
      });
    });

    it("assigns a created task only to its reserved composer", () => {
      store().startCreating(2, "session-2");

      expect(store().finishCreating("stale-session", "t1")).toBe(false);
      expect(store().finishCreating("session-2", "t1")).toBe(true);
      expect(store().cells[2]).toBe("t1");
      expect(store().composer).toBeNull();
    });

    it("does not overwrite a tile replaced while creation was pending", () => {
      store().startCreating(2, "session-2");
      store().assignTask(2, "replacement");

      expect(store().cells[2]).toBeNull();
      expect(store().finishCreating("session-2", "created")).toBe(true);
      expect(store().cells[2]).toBe("created");
    });

    it("rejects bulk placement while a tile is composing", () => {
      store().startCreating(1, "session-1");

      store().applyPlacement({
        layout: "2x2",
        cells: ["t1", "t2", null, null],
      });

      expect(store().cells).toEqual([null, null, null, null]);
      expect(store().composer).toEqual({
        cellIndex: 1,
        sessionId: "session-1",
      });
    });

    it("does not clear the grid while a tile is composing", () => {
      useCommandCenterStore.setState({ cells: ["t1", null, null, null] });
      store().startCreating(1, "session-1");

      store().clearAll();

      expect(store().cells).toEqual(["t1", null, null, null]);
      expect(store().composer?.sessionId).toBe("session-1");
    });
  });
});
