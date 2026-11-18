import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CommandCenterView } from "./CommandCenterView";

const mocks = vi.hoisted(() => ({
  markAsViewed: vi.fn(),
  timestampsReady: false,
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("../../../hooks/useSetHeaderContent", () => ({
  useSetHeaderContent: vi.fn(),
}));
vi.mock("../../sidebar/useTaskViewed", () => ({
  useTaskViewed: () => ({
    markAsViewed: mocks.markAsViewed,
    timestamps: {
      viewed: { lastViewedAt: 1, lastActivityAt: 1 },
    },
    timestampsReady: mocks.timestampsReady,
  }),
}));
vi.mock("../commandCenterStore", () => ({
  useCommandCenterStore: (selector: (state: { layout: "2x2" }) => unknown) =>
    selector({ layout: "2x2" }),
}));
vi.mock("../hooks/useAutofillCommandCenter", () => ({
  useAutofillCommandCenter: vi.fn(),
}));
vi.mock("../hooks/useCommandCenterData", () => ({
  useCommandCenterData: () => ({
    cells: [
      {
        cellIndex: 0,
        taskId: "viewed",
        task: {},
        canvasId: null,
        terminalId: null,
        isBrainrot: false,
      },
      {
        cellIndex: 1,
        taskId: "new",
        task: {},
        canvasId: null,
        terminalId: null,
        isBrainrot: false,
      },
    ],
    summary: {
      total: 2,
      running: 0,
      waiting: 0,
      idle: 2,
      error: 0,
      completed: 0,
    },
  }),
}));
vi.mock("./CommandCenterGrid", () => ({ CommandCenterGrid: () => null }));
vi.mock("./CommandCenterToolbar", () => ({
  CommandCenterToolbar: () => null,
}));

describe("CommandCenterView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.timestampsReady = false;
  });

  it.each([
    ["does not initialize views after a failed timestamp load", false, []],
    ["initializes missing views after timestamps load", true, ["new"]],
  ])("%s", (_, timestampsReady, expectedTaskIds) => {
    mocks.timestampsReady = timestampsReady;

    render(<CommandCenterView />);

    expect(mocks.markAsViewed.mock.calls.map(([taskId]) => taskId)).toEqual(
      expectedTaskIds,
    );
  });
});
