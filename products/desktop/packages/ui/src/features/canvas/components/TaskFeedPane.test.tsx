import type { Task } from "@posthog/shared/domain-types";
import { Theme } from "@radix-ui/themes";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));
vi.mock("@posthog/ui/features/archive/useArchivedTaskIds", () => ({
  useArchivedTaskIds: () => new Set<string>(),
}));
vi.mock("@posthog/ui/features/archive/useArchiveTask", () => ({
  useArchiveTask: () => ({ archiveTask: vi.fn() }),
}));
vi.mock("@posthog/ui/features/sidebar/usePinnedTasks", () => ({
  usePinnedTasks: () => ({
    pinnedTaskIds: new Set<string>(),
    togglePin: vi.fn(),
    setPinnedMany: vi.fn(),
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelItems", () => ({
  useChannelSessionFacts: () => ({
    needsInputTaskIds: new Set<string>(),
    viewedTimestamps: {},
    workspaceByTaskId: new Map(),
  }),
}));
vi.mock("@posthog/ui/features/command-center/commandCenterStore", () => ({
  useCommandCenterStore: () => [] as string[],
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelItemRow", () => ({
  ChannelItemRow: ({
    item,
    actions,
  }: {
    item: { id: string; title: string };
    actions: { open: (item: { id: string; title: string }) => void };
  }) => (
    <button type="button" onClick={() => actions.open(item)}>
      {item.title}
    </button>
  ),
}));
vi.mock("@posthog/ui/features/canvas/components/FeedQueryInput", () => ({
  FeedQueryHighlight: ({ query }: { query: string }) => <span>{query}</span>,
}));
vi.mock("@posthog/ui/features/canvas/components/TaskFeedModal", () => ({
  TaskFeedModal: ({ open }: { open: boolean }) =>
    open ? <div>Edit saved search</div> : null,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskFeedResults", () => ({
  useTaskFeedResults: () => ({
    error: null,
    errorMessage: null,
    isComplete: true,
    isLoading: false,
    tasks: [
      {
        id: "task-1",
        title: "Invoice total rounds down",
        channel: "channel-1",
        created_at: "2026-08-20T00:00:00Z",
        updated_at: "2026-08-21T00:00:00Z",
      } as Task,
    ],
  }),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { useTaskFeedSelectionStore } from "@posthog/ui/features/canvas/stores/taskFeedSelectionStore";
import { useTaskFeedsStore } from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { TaskFeedPane } from "./TaskFeedPane";

vi.mock("@posthog/ui/features/canvas/hooks/useProjectTaskFeeds", () => ({
  useProjectTaskFeed: (feedId: string) =>
    useTaskFeedsStore.getState().feeds.find((feed) => feed.id === feedId),
}));

describe("TaskFeedPane", () => {
  beforeEach(() => {
    useTaskFeedSelectionStore.setState({ selected: null });
    useTaskFeedsStore.setState({
      feeds: [
        {
          id: "feed-1",
          projectId: 1,
          ownerId: "user-1",
          name: "Billing work",
          query: "billing",
          createdAt: "2026-08-01T00:00:00Z",
        },
      ],
    });
  });

  it("selects a match into the detail pane instead of navigating", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <TaskFeedPane feedId="feed-1" />
      </Theme>,
    );

    await user.click(screen.getByText("Invoice total rounds down"));

    expect(useTaskFeedSelectionStore.getState().selected).toEqual({
      feedId: "feed-1",
      taskId: "task-1",
      channelId: "channel-1",
    });
  });

  it("drops the selection when the search is deleted", async () => {
    const user = userEvent.setup();
    useTaskFeedSelectionStore.setState({
      selected: { feedId: "feed-1", taskId: "task-1", channelId: null },
    });
    render(
      <Theme>
        <TaskFeedPane feedId="feed-1" />
      </Theme>,
    );

    await user.click(screen.getByLabelText("Delete saved search…"));
    const dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByText("Delete"));

    expect(useTaskFeedsStore.getState().feeds).toEqual([]);
    expect(useTaskFeedSelectionStore.getState().selected).toBeNull();
  });
});
