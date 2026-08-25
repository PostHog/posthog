import { describe, expect, it } from "vitest";
import {
  BRAINROT_CELL,
  clampZoom,
  countActiveTaskCells,
  getCanvasCellId,
  getCellCount,
  getCellSessionId,
  getExpandedLayout,
  getExpansionCellIndex,
  getGridDimensions,
  getLayoutToFit,
  getOptimalLayout,
  getTerminalCellCwd,
  getTerminalCellId,
  isBrainrotCell,
  isCanvasCell,
  isTerminalCell,
  makeCanvasCellValue,
  makeTerminalCellValue,
  reflowCells,
  resizeCells,
} from "./grid";

describe("getGridDimensions / getCellCount", () => {
  it.each([
    { preset: "1x1", cols: 1, rows: 1, count: 1 },
    { preset: "2x1", cols: 2, rows: 1, count: 2 },
    { preset: "3x1", cols: 3, rows: 1, count: 3 },
    { preset: "1x2", cols: 1, rows: 2, count: 2 },
    { preset: "2x2", cols: 2, rows: 2, count: 4 },
    { preset: "3x2", cols: 3, rows: 2, count: 6 },
    { preset: "3x3", cols: 3, rows: 3, count: 9 },
  ] as const)(
    "$preset -> $cols x $rows = $count",
    ({ preset, cols, rows, count }) => {
      expect(getGridDimensions(preset)).toEqual({ cols, rows });
      expect(getCellCount(preset)).toBe(count);
    },
  );
});

describe("getExpansionCellIndex", () => {
  // Widening 2x2 to 3x2 puts the new column at indices 2 and 5; growing it to
  // 2x3 puts the new row at 4 and 5.
  it.each([
    { expanded: "3x2", direction: "horizontal", slot: 0, expected: 2 },
    { expanded: "3x2", direction: "horizontal", slot: 1, expected: 5 },
    { expanded: "2x3", direction: "vertical", slot: 0, expected: 4 },
    { expanded: "2x3", direction: "vertical", slot: 1, expected: 5 },
  ] as const)(
    "$expanded $direction slot $slot -> $expected",
    ({ expanded, direction, slot, expected }) => {
      expect(getExpansionCellIndex(expanded, direction, slot)).toBe(expected);
    },
  );
});

describe("getOptimalLayout", () => {
  it.each([
    [0, "1x1"],
    [1, "1x1"],
    [2, "2x1"],
    [3, "2x2"],
    [4, "2x2"],
    [5, "3x2"],
    [6, "3x2"],
    [7, "3x3"],
    [9, "3x3"],
    [12, "3x3"],
  ] as const)("fits %i tiles in %s", (count, expected) => {
    expect(getOptimalLayout(count)).toBe(expected);
  });
});

describe("getLayoutToFit", () => {
  it.each([
    { current: "2x2", needed: 4, expected: "2x2" },
    { current: "2x2", needed: 2, expected: "2x2" },
    { current: "2x2", needed: 5, expected: "3x2" },
    { current: "1x1", needed: 4, expected: "2x2" },
    { current: "1x1", needed: 2, expected: "2x1" },
    { current: "3x1", needed: 5, expected: "3x2" },
    { current: "2x2", needed: 20, expected: "3x3" },
  ] as const)(
    "grows $current to $expected for $needed tiles",
    ({ current, needed, expected }) => {
      expect(getLayoutToFit(current, needed)).toBe(expected);
    },
  );

  // getOptimalLayout(5) is 3x2, which would cost 1x3 its third row on reflow.
  it.each([
    { current: "1x3", needed: 5, expected: "2x3" },
    { current: "1x2", needed: 5, expected: "3x2" },
  ] as const)(
    "never shrinks an axis: $current for $needed tiles",
    ({ current, needed, expected }) => {
      const result = getLayoutToFit(current, needed);
      expect(result).toBe(expected);
      const before = getGridDimensions(current);
      const after = getGridDimensions(result);
      expect(after.cols).toBeGreaterThanOrEqual(before.cols);
      expect(after.rows).toBeGreaterThanOrEqual(before.rows);
    },
  );
});

describe("getExpandedLayout", () => {
  it.each([
    ["1x1", "horizontal", "2x1"],
    ["1x1", "vertical", "1x2"],
    ["2x2", "horizontal", "3x2"],
    ["2x2", "vertical", "2x3"],
    ["3x1", "horizontal", null],
    ["1x3", "vertical", null],
    ["3x3", "horizontal", null],
    ["3x3", "vertical", null],
  ] as const)("expands %s %s to %s", (layout, direction, expected) => {
    expect(getExpandedLayout(layout, direction)).toBe(expected);
  });
});

describe("reflowCells", () => {
  // Row-major storage means a column change moves every row's start: 2x2
  // [a,b / c,d] widening to 3x2 must keep c and d on row two.
  it("keeps cells in the same row and column when a column is added", () => {
    expect(reflowCells(["a", "b", "c", "d"], "2x2", "3x2")).toEqual([
      "a",
      "b",
      null,
      "c",
      "d",
      null,
    ]);
  });

  it("appends empty cells when a row is added", () => {
    expect(reflowCells(["a", "b"], "2x1", "2x2")).toEqual([
      "a",
      "b",
      null,
      null,
    ]);
  });

  it("drops cells that fall outside a narrower grid", () => {
    expect(reflowCells(["a", "b", "c", "d", "e", "f"], "3x2", "2x2")).toEqual([
      "a",
      "b",
      "d",
      "e",
    ]);
  });
});

describe("resizeCells", () => {
  it("returns same array when count matches", () => {
    const cells = ["a", null, "b"];
    expect(resizeCells(cells, 3)).toBe(cells);
  });

  it("truncates when shrinking", () => {
    expect(resizeCells(["a", "b", "c", "d"], 2)).toEqual(["a", "b"]);
  });

  it("pads with null when growing", () => {
    expect(resizeCells(["a"], 4)).toEqual(["a", null, null, null]);
  });
});

describe("clampZoom", () => {
  it.each([
    { input: 0.1, expected: 0.5 },
    { input: 2, expected: 1.5 },
    { input: 1.0, expected: 1 },
    { input: 1.04, expected: 1 },
    { input: 1.06, expected: 1.1 },
  ])("clamps and rounds $input -> $expected", ({ input, expected }) => {
    expect(clampZoom(input)).toBe(expected);
  });
});

describe("isBrainrotCell", () => {
  it.each([
    { value: BRAINROT_CELL, expected: true },
    { value: "some-task-uuid", expected: false },
    { value: null, expected: false },
  ])("$value -> $expected", ({ value, expected }) => {
    expect(isBrainrotCell(value)).toBe(expected);
  });
});

describe("canvas cells", () => {
  it("round-trips a canvas id through the cell value", () => {
    const value = makeCanvasCellValue("canvas-1");
    expect(isCanvasCell(value)).toBe(true);
    expect(getCanvasCellId(value)).toBe("canvas-1");
  });

  it.each([
    { value: "some-task-uuid", expected: false },
    { value: BRAINROT_CELL, expected: false },
    { value: makeTerminalCellValue("abc123"), expected: false },
    { value: null, expected: false },
  ])("isCanvasCell($value) -> $expected", ({ value, expected }) => {
    expect(isCanvasCell(value)).toBe(expected);
    if (!expected) expect(getCanvasCellId(value)).toBeNull();
  });
});

describe("terminal cells", () => {
  it("round-trips a terminal id through the cell value", () => {
    const value = makeTerminalCellValue("abc123");
    expect(isTerminalCell(value)).toBe(true);
    expect(getTerminalCellId(value)).toBe("abc123");
    expect(getTerminalCellCwd(value)).toBeNull();
  });

  it("round-trips a terminal id and cwd through the cell value", () => {
    const value = makeTerminalCellValue("abc123", "/Users/me/my:repo");
    expect(isTerminalCell(value)).toBe(true);
    expect(getTerminalCellId(value)).toBe("abc123");
    expect(getTerminalCellCwd(value)).toBe("/Users/me/my:repo");
  });

  it.each([
    { value: "some-task-uuid", expected: false },
    { value: BRAINROT_CELL, expected: false },
    { value: null, expected: false },
  ])("isTerminalCell($value) -> $expected", ({ value, expected }) => {
    expect(isTerminalCell(value)).toBe(expected);
    expect(getTerminalCellId(value)).toBeNull();
  });
});

describe("getCellSessionId", () => {
  it("formats the cell session id", () => {
    expect(getCellSessionId(2)).toBe("cc-cell-2");
  });
});

describe("countActiveTaskCells", () => {
  const live = new Set(["task-1", "task-2"]);

  it("counts only cells whose task still exists", () => {
    expect(countActiveTaskCells(["task-1", "task-2"], live)).toBe(2);
  });

  // Cells are persisted and only pruned on archive, so a deleted task's id
  // lingers forever — counting the array's non-empty entries would never drop.
  it("ignores a task that has since been deleted", () => {
    expect(countActiveTaskCells(["task-1", "deleted-task"], live)).toBe(1);
  });

  it.each([
    { name: "empty cells", cells: [null, null] },
    { name: "the brainrot sentinel", cells: [BRAINROT_CELL] },
    { name: "terminal cells", cells: [makeTerminalCellValue("abc123")] },
    { name: "canvas cells", cells: [makeCanvasCellValue("canvas-1")] },
  ])("does not count $name", ({ cells }) => {
    expect(countActiveTaskCells(cells, live)).toBe(0);
  });

  it("counts a mixed grid correctly", () => {
    expect(
      countActiveTaskCells(
        [
          null,
          BRAINROT_CELL,
          "task-1",
          "deleted",
          makeTerminalCellValue("t"),
          makeCanvasCellValue("canvas-1"),
        ],
        live,
      ),
    ).toBe(1);
  });
});
