import { describe, expect, it } from "vitest";
import {
  BRAINROT_CELL,
  clampZoom,
  countActiveTaskCells,
  getCellCount,
  getCellSessionId,
  getGridDimensions,
  getTerminalCellCwd,
  getTerminalCellId,
  isBrainrotCell,
  isTerminalCell,
  makeTerminalCellValue,
  resizeCells,
} from "./grid";

describe("getGridDimensions / getCellCount", () => {
  it.each([
    { preset: "1x1", cols: 1, rows: 1, count: 1 },
    { preset: "2x1", cols: 2, rows: 1, count: 2 },
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
  ])("does not count $name", ({ cells }) => {
    expect(countActiveTaskCells(cells, live)).toBe(0);
  });

  it("counts a mixed grid correctly", () => {
    expect(
      countActiveTaskCells(
        [null, BRAINROT_CELL, "task-1", "deleted", makeTerminalCellValue("t")],
        live,
      ),
    ).toBe(1);
  });
});
