import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { buildCommandCenterCells } from "./cells";
import { BRAINROT_CELL, makeTerminalCellValue } from "./grid";

const EMPTY_INPUT = {
  taskById: new Map<string, Task>(),
  sessionByTaskId: new Map(),
  workspaces: undefined,
};

describe("buildCommandCenterCells", () => {
  it.each([
    {
      name: "brainrot sentinel cell has isBrainrot and no task",
      input: BRAINROT_CELL,
      expected: {
        cellIndex: 0,
        isBrainrot: true,
        taskId: null,
        task: undefined,
        status: "idle",
      },
    },
    {
      name: "terminal cell exposes its terminal id and no task",
      input: makeTerminalCellValue("term-1"),
      expected: {
        cellIndex: 0,
        terminalId: "term-1",
        isBrainrot: false,
        taskId: null,
        task: undefined,
        status: "idle",
      },
    },
    {
      name: "empty cell is a non-brainrot empty slot",
      input: null,
      expected: { isBrainrot: false, taskId: null, terminalId: null },
    },
    {
      name: "unknown task id is a non-brainrot cell",
      input: "missing",
      expected: { isBrainrot: false, taskId: "missing" },
    },
  ])("$name", ({ input, expected }) => {
    const [cell] = buildCommandCenterCells([input], EMPTY_INPUT);
    expect(cell).toMatchObject(expected);
  });
});
