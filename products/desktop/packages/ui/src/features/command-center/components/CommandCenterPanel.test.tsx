import type { Task } from "@posthog/shared/domain-types";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CommandCenterCellData } from "../hooks/useCommandCenterData";

const mocks = vi.hoisted(() => ({
  openTask: vi.fn(),
  setDraft: vi.fn(),
  clearAutoresearchDraft: vi.fn(),
  currentUserUuid: "user-1",
  taskCreatedCallback: null as ((task: Task) => void) | null,
  authState: {
    status: "authenticated",
    cloudRegion: "us",
    currentProjectId: 2,
  },
  createdTask: { id: "task-2", title: "Composed in a tile" },
  store: {
    layout: "2x2",
    cells: [null, null, null, null] as (string | null)[],
    composer: null as { cellIndex: number; sessionId: string } | null,
    finishCreating: vi.fn(() => true),
    clearCell: vi.fn(),
    setBrainrotCell: vi.fn(),
    setTerminalCell: vi.fn(),
    startCreating: vi.fn(),
    stopCreating: vi.fn(),
  },
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
vi.mock("../../message-editor/draftStore", () => {
  const state = { actions: { setDraft: mocks.setDraft } };
  return {
    useDraftStore: Object.assign(
      (selector: (store: typeof state) => unknown) => selector(state),
      { getState: () => state },
    ),
  };
});
vi.mock("../../auth/store", () => ({
  useAuthStateValue: (selector: (state: typeof mocks.authState) => unknown) =>
    selector(mocks.authState),
}));
vi.mock("../../auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({}),
}));
vi.mock("../../auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { uuid: mocks.currentUserUuid } }),
}));
vi.mock("../../autoresearch/autoresearchDraftStore", () => ({
  useAutoresearchDraftStore: {
    getState: () => ({ clearDraft: mocks.clearAutoresearchDraft }),
  },
}));
vi.mock("../../settings/settingsStore", () => ({
  useSettingsStore: (selector: (state: unknown) => unknown) =>
    selector({ brainrotMode: false }),
}));
vi.mock("../../task-detail/components/TaskInput", () => ({
  TaskInput: ({
    onTaskCreated,
    showNewTaskSuggestions,
    allowNoRepo,
  }: {
    onTaskCreated?: (task: Task) => void;
    showNewTaskSuggestions?: boolean;
    allowNoRepo?: boolean;
  }) => {
    mocks.taskCreatedCallback = onTaskCreated ?? null;
    return (
      <div
        data-allow-no-repo={allowNoRepo}
        data-suggestions={showNewTaskSuggestions}
      >
        <button
          type="button"
          onClick={() => onTaskCreated?.(mocks.createdTask as Task)}
        >
          Send
        </button>
      </div>
    );
  },
}));
vi.mock("../commandCenterStore", () => ({
  useCommandCenterStore: (selector: (state: unknown) => unknown) =>
    selector(mocks.store),
  getCellSessionId: (scope: string, cellIndex: number) =>
    `cc-cell-${scope}-${cellIndex}`,
}));
vi.mock("./CommandCenterPRButton", () => ({
  CommandCenterPRButton: () => null,
}));
vi.mock("./TaskSelector", () => ({
  TaskSelector: ({
    children,
    onNewTask,
  }: {
    children: ReactNode;
    onNewTask?: () => void;
  }) => (
    <>
      {children}
      {onNewTask && (
        <button type="button" onClick={onNewTask}>
          New task
        </button>
      )}
    </>
  ),
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

const emptyCell = {
  ...cell,
  cellIndex: 2,
  taskId: null,
  task: undefined,
} satisfies CommandCenterCellData;

describe("CommandCenterPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.authState.cloudRegion = "us";
    mocks.authState.currentProjectId = 2;
    mocks.currentUserUuid = "user-1";
    mocks.taskCreatedCallback = null;
    mocks.store.composer = null;
    mocks.store.finishCreating.mockReturnValue(true);
  });

  it("preserves the task's space when opening it", () => {
    render(<CommandCenterPanel cell={cell} isActiveSession={false} />);

    fireEvent.click(screen.getByTitle("Open task"));

    expect(mocks.openTask).toHaveBeenCalledWith(task, {
      channelId: "channel-1",
    });
  });

  // Sending the user to the full-page composer instead abandons the grid they
  // laid out, which is the whole point of working in Command Center.
  it("starts a new task inside the tile that asked for one", () => {
    render(<CommandCenterPanel cell={emptyCell} isActiveSession={false} />);

    fireEvent.click(screen.getByRole("button", { name: "New task" }));

    expect(mocks.store.startCreating).toHaveBeenCalledWith(
      2,
      "cc-cell-us:2:user-1-2",
    );
  });

  // Without this the task is created but never claims a tile, so its session
  // renders nowhere.
  it("keeps a task composed in a tile in that tile", () => {
    mocks.store.composer = {
      cellIndex: 2,
      sessionId: "cc-cell-us:2:user-1-2",
    };
    render(<CommandCenterPanel cell={emptyCell} isActiveSession={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(mocks.store.finishCreating).toHaveBeenCalledWith(
      "cc-cell-us:2:user-1-2",
      "task-2",
    );
    expect(screen.getByText("Send").parentElement).toHaveAttribute(
      "data-suggestions",
      "false",
    );
    expect(screen.getByText("Send").parentElement).toHaveAttribute(
      "data-allow-no-repo",
      "true",
    );
  });

  it("does not open a created task when the auth scope changed", () => {
    mocks.store.composer = {
      cellIndex: 2,
      sessionId: "cc-cell-us:2:user-1-2",
    };
    const { rerender } = render(
      <CommandCenterPanel cell={emptyCell} isActiveSession={false} />,
    );
    const taskCreated = mocks.taskCreatedCallback;
    mocks.currentUserUuid = "user-2";
    rerender(<CommandCenterPanel cell={emptyCell} isActiveSession={false} />);

    taskCreated?.(mocks.createdTask as Task);

    expect(mocks.store.finishCreating).not.toHaveBeenCalled();
    expect(mocks.store.stopCreating).toHaveBeenCalledWith(
      "cc-cell-us:2:user-1-2",
    );
    expect(mocks.openTask).not.toHaveBeenCalled();
  });

  it("opens a created task when its tile is no longer reserved", () => {
    mocks.store.composer = {
      cellIndex: 2,
      sessionId: "cc-cell-us:2:user-1-2",
    };
    mocks.store.finishCreating.mockReturnValue(false);
    render(<CommandCenterPanel cell={emptyCell} isActiveSession={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(mocks.openTask).toHaveBeenCalledWith(mocks.createdTask);
  });

  it("preserves the draft when leaving the command center", () => {
    mocks.store.composer = {
      cellIndex: 2,
      sessionId: "cc-cell-us:2:user-1-2",
    };
    const { unmount } = render(
      <CommandCenterPanel cell={emptyCell} isActiveSession={false} />,
    );

    unmount();

    expect(mocks.setDraft).not.toHaveBeenCalled();
    expect(mocks.clearAutoresearchDraft).not.toHaveBeenCalled();
  });

  it("clears all session drafts when canceling", () => {
    mocks.store.composer = {
      cellIndex: 2,
      sessionId: "cc-cell-us:2:user-1-2",
    };
    render(<CommandCenterPanel cell={emptyCell} isActiveSession={false} />);

    fireEvent.click(screen.getByTitle("Cancel"));

    expect(mocks.store.stopCreating).toHaveBeenCalledWith(
      "cc-cell-us:2:user-1-2",
    );
    expect(mocks.setDraft).toHaveBeenCalledWith("cc-cell-us:2:user-1-2", null);
    expect(mocks.clearAutoresearchDraft).toHaveBeenCalledWith(
      "cc-cell-us:2:user-1-2",
    );
  });
});
