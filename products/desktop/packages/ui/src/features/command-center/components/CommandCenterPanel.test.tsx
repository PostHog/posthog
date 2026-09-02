import type { Task } from "@posthog/shared/domain-types";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CommandCenterCellData } from "../hooks/useCommandCenterData";

const mocks = vi.hoisted(() => ({
  openTask: vi.fn(),
}));

vi.mock("@posthog/ui/router/useOpenTask", () => ({
  openTask: (...args: unknown[]) => mocks.openTask(...args),
}));
vi.mock("@posthog/ui/features/canvas/freeform/FreeformCanvasView", () => ({
  FreeformCanvasView: () => null,
}));
vi.mock("@posthog/ui/features/canvas/grid/GridCanvasView", () => ({
  GridCanvasView: () => null,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useDashboard: () => ({ dashboard: null, isLoading: false }),
}));
vi.mock("@posthog/ui/features/terminal/destroyShellTerminal", () => ({
  destroyShellTerminal: vi.fn(),
}));
vi.mock("@posthog/ui/features/terminal/ShellTerminal", () => ({
  ShellTerminal: () => null,
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/shell/useHostCapabilities", () => ({
  useHostCapabilities: () => ({ localWorkspaces: true }),
}));
vi.mock("@posthog/ui/utils/random", () => ({
  secureRandomString: () => "random",
}));
vi.mock("@radix-ui/themes", () => ({
  Flex: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Text: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
}));
vi.mock("../../folders/useFolders", () => ({
  useFolders: () => ({
    getRecentFolders: () => [],
    getFolderDisplayName: () => "",
  }),
}));
vi.mock("../../git-interaction/useCloudPrUrl", () => ({
  useCloudPrUrl: () => null,
}));
vi.mock("../../sessions/components/EmbeddedSessionView", () => ({
  EmbeddedSessionView: () => <div>session</div>,
}));
vi.mock("../../sidebar/components/items/TaskIcon", () => ({
  TaskIcon: () => null,
}));
vi.mock("../../sidebar/useTaskPrStatus", () => ({
  useTaskPrStatus: () => ({ prState: null, hasDiff: false }),
}));
vi.mock("../commandCenterStore", () => ({
  useCommandCenterStore: (
    selector: (state: { clearCell: () => void }) => unknown,
  ) => selector({ clearCell: vi.fn() }),
}));
vi.mock("./CommandCenterPRButton", () => ({
  CommandCenterPRButton: () => null,
}));
vi.mock("./TaskSelector", () => ({
  TaskSelector: ({ children }: { children: ReactNode }) => children,
}));

import { CommandCenterPanel } from "./CommandCenterPanel";

const task = {
  id: "task-1",
  task_number: 1,
  slug: "task-1",
  title: "Fix Command Center",
  description: "",
  created_at: "2026-08-28T00:00:00.000Z",
  updated_at: "2026-08-28T00:00:00.000Z",
  origin_product: "code",
  channel: "channel-1",
} satisfies Task;

const cell = {
  cellIndex: 0,
  taskId: task.id,
  task,
  session: undefined,
  status: "idle",
  repoName: null,
  workspaceMode: null,
  isBrainrot: false,
  canvasId: null,
  terminalId: null,
  terminalCwd: null,
} satisfies CommandCenterCellData;

describe("CommandCenterPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("preserves the task's space when opening it", () => {
    render(<CommandCenterPanel cell={cell} isActiveSession={false} />);

    fireEvent.click(screen.getByTitle("Open task"));

    expect(mocks.openTask).toHaveBeenCalledWith(task, {
      channelId: "channel-1",
    });
  });
});
