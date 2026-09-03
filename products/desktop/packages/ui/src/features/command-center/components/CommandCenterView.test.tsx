import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  hasFocus: vi.fn(),
  markAsViewed: vi.fn(),
  timestamps: {
    "task-1": { lastViewedAt: null, lastActivityAt: 1 as number | null },
    "task-2": { lastViewedAt: null, lastActivityAt: 1 as number | null },
  },
  cells: [
    {
      cellIndex: 0,
      taskId: "task-1",
      task: {},
      canvasId: null,
      terminalId: null,
      isBrainrot: false,
    },
    {
      cellIndex: 1,
      taskId: "task-2",
      task: {},
      canvasId: null,
      terminalId: null,
      isBrainrot: false,
    },
  ],
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => ({ hasFocus: mocks.hasFocus }),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("../../../hooks/useSetHeaderContent", () => ({
  useSetHeaderContent: vi.fn(),
}));
vi.mock("../../sidebar/useTaskViewed", () => ({
  useTaskViewed: () => ({
    markAsViewed: mocks.markAsViewed,
    timestamps: mocks.timestamps,
  }),
}));
vi.mock("../commandCenterStore", () => ({
  useCommandCenterStore: () => "2x2",
}));
vi.mock("../hooks/useAutofillCommandCenter", () => ({
  useAutofillCommandCenter: vi.fn(),
}));
vi.mock("../hooks/useCommandCenterData", () => ({
  useCommandCenterData: () => ({ cells: mocks.cells, summary: {} }),
}));
vi.mock("./CommandCenterGrid", () => ({ CommandCenterGrid: () => null }));
vi.mock("./CommandCenterToolbar", () => ({
  CommandCenterToolbar: () => null,
}));

import { CommandCenterView } from "./CommandCenterView";

describe("CommandCenterView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.timestamps["task-1"].lastActivityAt = 1;
    mocks.timestamps["task-2"].lastActivityAt = 1;
  });

  it.each([
    ["focused", true, ["task-1", "task-2"]],
    ["unfocused", false, []],
  ])(
    "keeps visible tasks read after activity when the app is %s",
    (_label, hasFocus, expectedTaskIds) => {
      mocks.hasFocus.mockReturnValue(hasFocus);
      const { rerender } = render(<CommandCenterView />);
      mocks.markAsViewed.mockClear();

      mocks.timestamps["task-1"].lastActivityAt = 2;
      rerender(<CommandCenterView />);

      expect(mocks.markAsViewed.mock.calls.map(([taskId]) => taskId)).toEqual(
        expectedTaskIds,
      );
    },
  );
});
