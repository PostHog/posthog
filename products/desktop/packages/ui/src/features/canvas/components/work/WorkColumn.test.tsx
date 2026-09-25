import {
  type ChannelItemModel,
  DESKTOP_SOURCE,
} from "@posthog/core/canvas/channelItems";
import { ChannelItemPreviewCardProvider } from "@posthog/ui/features/canvas/components/ChannelItemHoverCard";
import { Theme } from "@radix-ui/themes";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  items: [] as { item: ChannelItemModel; channelId: string | undefined }[],
  navigate: {
    toChannelTask: vi.fn(),
    toChannelDashboard: vi.fn(),
    toTaskDetail: vi.fn(),
    toChannel: vi.fn(),
    toSpaces: vi.fn(),
  },
}));

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToChannel: mocks.navigate.toChannel,
  navigateToChannelDashboard: mocks.navigate.toChannelDashboard,
  navigateToChannelTask: mocks.navigate.toChannelTask,
  navigateToSpaces: mocks.navigate.toSpaces,
  navigateToTaskDetail: mocks.navigate.toTaskDetail,
}));

vi.mock("@posthog/ui/features/canvas/hooks/useRecentWorkItems", () => ({
  useRecentWorkItems: () => ({ items: mocks.items, isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelItems", () => ({
  useChannelItemActions: ({
    open,
  }: {
    open: (item: ChannelItemModel) => void;
  }) => ({
    open,
    togglePin: vi.fn(),
    setPinned: vi.fn(),
    archive: vi.fn(),
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [], isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useRecentSpaceTasks", () => ({
  useSpacePresence: () => new Map(),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useUnreadSessionCount", () => ({
  useUnreadSessionCount: () => () => 0,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useBlockedSessionCount", () => ({
  useBlockedSessionCount: () => () => 0,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useUnreadChannels", () => ({
  useIsChannelUnread: () => () => false,
}));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
  useRouterState: () => "/spaces/channel-1",
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { id: 1, uuid: "me-uuid" } }),
}));
vi.mock("@posthog/ui/features/tasks/useTaskMutations", () => ({
  useRenameTask: () => ({ renameTask: vi.fn() }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTaskStatus", () => ({
  useChannelTaskStatus: () => null,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasksRunState", () => ({
  useChannelTasksRunState: () => [],
}));
// What each bulk action does has its own suite; this one is about whether the
// column offers them at all, so the bar only needs its count to be real.
vi.mock("@posthog/ui/features/sidebar/useSidebarBulkActions", () => ({
  useSidebarBulkActions: (selectedTaskIds: string[]) => ({
    selectedCount: selectedTaskIds.length,
    pinDirection: "pin",
    pinLabel: "Pin",
    channels: [],
    archiveDisabledReason: null,
    pinDisabledReason: null,
    commandCenterDisabledReason: null,
    fileDisabledReason: null,
    isArchiving: false,
    isPinning: false,
    isFiling: false,
    pinSelected: vi.fn(),
    addSelectedToCommandCenter: vi.fn(),
    fileSelected: vi.fn(),
    archiveSelected: vi.fn(),
  }),
}));
vi.mock("@posthog/ui/features/canvas/components/CreateChannelModal", () => ({
  CreateChannelModal: () => null,
}));
vi.mock(
  "@posthog/ui/features/sidebar/components/EditListItemAppearanceDialog",
  () => ({ EditListItemAppearanceDialog: () => null }),
);
vi.mock("@posthog/ui/features/browser-tabs/useOpenBrowserTab", () => ({
  useOpenBrowserTab: () => vi.fn(),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useFileTaskToChannel", () => ({
  useFileTaskToChannel: () => vi.fn(),
}));

import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";
import { WorkColumn } from "./WorkColumn";

function entry(index: number): {
  item: ChannelItemModel;
  channelId: string | undefined;
} {
  return {
    channelId: "channel-1",
    item: {
      key: `task:task-${index}`,
      kind: "task",
      id: `task-${index}`,
      title: `Session ${index}`,
      ts: Date.parse("2026-07-17T12:00:00.000Z") - index * 60_000,
      createdAt: Date.parse("2026-07-16T12:00:00.000Z"),
      pinned: false,
      rawStatus: null,
      environment: null,
      source: DESKTOP_SOURCE,
      needsInput: false,
      unread: false,
      authorUser: null,
      authorName: null,
      authorUuid: "me-uuid",
      templateId: null,
      repository: null,
      branch: null,
      task: null,
    },
  };
}

function renderColumn() {
  return render(
    <Theme>
      <ChannelItemPreviewCardProvider>
        <WorkColumn />
      </ChannelItemPreviewCardProvider>
    </Theme>,
  );
}

// By text rather than by role: the column renders a whole sidebar, and a role
// query walks all of it computing accessible names.
function row(index: number): HTMLElement {
  const label = screen.getByText(`Session ${index}`);
  const option = label.closest('[role="option"]');
  if (!(option instanceof HTMLElement)) throw new Error("row is not an option");
  return option;
}

const navigate = mocks.navigate;

beforeEach(() => {
  for (const spy of Object.values(mocks.navigate)) spy.mockClear();
  mocks.items = [1, 2, 3, 4, 5].map(entry);
  useTaskSelectionStore.setState({ selectedTaskIds: [], lastClickedId: null });
});

afterEach(cleanup);

describe("WorkColumn", () => {
  it("opens a session on a plain click", () => {
    renderColumn();

    fireEvent.click(row(1));

    expect(navigate.toChannelTask).toHaveBeenCalledWith("channel-1", "task-1");
    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([]);
  });

  it("adds and drops rows with a modifier click, without opening them", () => {
    renderColumn();

    fireEvent.click(row(1), { metaKey: true });
    fireEvent.click(row(3), { metaKey: true });

    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([
      "task-1",
      "task-3",
    ]);
    expect(navigate.toChannelTask).not.toHaveBeenCalled();

    fireEvent.click(row(3), { metaKey: true });

    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([
      "task-1",
    ]);
  });

  it("extends the selection to a whole range with shift", () => {
    renderColumn();

    fireEvent.click(row(1), { metaKey: true });
    fireEvent.click(row(4), { shiftKey: true });

    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([
      "task-1",
      "task-2",
      "task-3",
      "task-4",
    ]);
  });

  it("offers the bulk bar for a selection and clears it on Escape", async () => {
    renderColumn();

    fireEvent.click(row(1), { metaKey: true });
    fireEvent.click(row(2), { metaKey: true });

    expect(screen.getByText("2 selected")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");

    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([]);
    expect(screen.queryByText("2 selected")).not.toBeInTheDocument();
  });
});
