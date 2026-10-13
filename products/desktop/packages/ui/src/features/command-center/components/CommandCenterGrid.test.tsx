import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CommandCenterCellData } from "../hooks/useCommandCenterData";

const mocks = vi.hoisted(() => ({
  markAsViewed: vi.fn(),
  setActiveCell: vi.fn(),
  setActiveTask: vi.fn(),
  store: {
    zoom: 1,
    activeCellIndex: null as number | null,
    pendingPlacement: null,
    composer: null,
    cancelPlacement: vi.fn(),
  },
}));

vi.mock("@posthog/ui/features/tasks/useLiveTaskIds", () => ({
  useLiveTaskIds: () => new Set<string>(),
}));
vi.mock("../../sidebar/useTaskViewed", () => ({
  useTaskViewed: () => ({ markAsViewed: mocks.markAsViewed }),
}));
vi.mock("../commandCenterStore", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("../commandCenterStore")>();
  return {
    ...original,
    useCommandCenterStore: (selector: (state: unknown) => unknown) =>
      selector({
        ...mocks.store,
        setActiveCell: mocks.setActiveCell,
        setActiveTask: mocks.setActiveTask,
      }),
  };
});
vi.mock("./CommandCenterPanel", () => ({
  CommandCenterPanel: () => <button type="button">Task tile</button>,
}));

import { CommandCenterGrid } from "./CommandCenterGrid";

const cell = {
  cellIndex: 0,
  taskId: "task-1",
  task: { id: "task-1", title: "Finished task" },
  session: undefined,
  status: "idle",
  repoName: null,
  workspaceMode: null,
  canvasId: null,
  isBrainrot: false,
  terminalId: null,
  terminalCwd: null,
  hasUnseenCompletion: true,
} as CommandCenterCellData;

describe("CommandCenterGrid", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("marks an unseen completion as viewed when its tile is clicked", () => {
    render(<CommandCenterGrid layout="1x1" cells={[cell]} />);

    fireEvent.click(screen.getByText("Task tile"));

    expect(mocks.markAsViewed).toHaveBeenCalledWith("task-1");
  });
});
