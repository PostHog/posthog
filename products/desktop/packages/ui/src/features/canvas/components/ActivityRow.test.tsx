import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({
  toChannelDashboard: vi.fn(),
  toChannelTask: vi.fn(),
  toTaskDetail: vi.fn(),
}));

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToChannelDashboard: navigation.toChannelDashboard,
  navigateToChannelTask: navigation.toChannelTask,
  navigateToTaskDetail: navigation.toTaskDetail,
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: [{ id: "channel-1", name: "Personal space", starred: false }],
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useFileTaskToChannel", () => ({
  useFileTaskToChannel: () => vi.fn(),
}));
vi.mock("@posthog/ui/features/browser-tabs/useOpenBrowserTab", () => ({
  useOpenBrowserTab: () => vi.fn(),
}));

import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { ActivityRow } from "./ActivityRow";
import { openActivityItem } from "./openActivityItem";
import type { TaskRowMenuProps } from "./TaskRowMenu";

function item(overrides: Partial<TaskActivityItem>): TaskActivityItem {
  return {
    id: "activity-1",
    taskId: "task-1",
    taskTitle: "Say hello",
    channelId: null,
    channelName: null,
    activityAt: "2026-07-27T10:00:00Z",
    activityKind: "message",
    snippet: "Hello!",
    author: null,
    messageId: "message-1",
    isUnread: true,
    ...overrides,
  };
}

const NO_BLOCKED_TASKS: ReadonlySet<string> = new Set();

function taskMenu(overrides: Partial<TaskRowMenuProps> = {}): TaskRowMenuProps {
  return {
    kind: "task",
    id: "task-1",
    title: "Say hello",
    isPinned: false,
    onTogglePin: vi.fn(),
    onArchive: vi.fn(),
    ...overrides,
  };
}

describe("ActivityRow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-27T10:00:00Z"));
    navigation.toChannelTask.mockReset();
    navigation.toChannelDashboard.mockReset();
    navigation.toTaskDetail.mockReset();
    useCommentNavigationStore.setState({
      focusByTask: {},
      resolutionsByTarget: {},
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("leads a completed activity row with the task title", () => {
    render(
      <ActivityRow
        menu={taskMenu()}
        item={item({
          activityKind: "completed",
          taskTitle: "Tell me a joke",
          channelName: "personal",
        })}
        onMarkRead={vi.fn()}
        onActivate={vi.fn()}
        blockedTaskIds={NO_BLOCKED_TASKS}
        compact
      />,
    );

    const title = screen.getByText("Tell me a joke");
    const metadata = screen.getByText("just now · Agent finished in");
    const spaceBadge = screen.getByText("Personal").closest(".quill-badge");
    expect(title.compareDocumentPosition(metadata)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    expect(spaceBadge).toHaveClass("quill-badge--variant-default");
    const row = title.closest("button");
    expect(row).toHaveAccessibleName(
      "Tell me a joke just now · Agent finished in Personal",
    );
    expect(row?.querySelector(".quill-avatar")).toHaveClass(
      "bg-primary",
      "text-primary-foreground",
      "size-4",
    );
    expect(row).not.toHaveClass("bg-primary/10");
    expect(row).not.toHaveClass("outline-primary/20");
    expect(screen.queryByTitle("New activity")).not.toBeInTheDocument();
  });

  it.each([
    { label: "unread", isUnread: true, laneClass: "pr-14" },
    { label: "read", isUnread: false, laneClass: "pr-8" },
  ])(
    "reserves a compact $label row's trailing lane for the actions it shows",
    ({ isUnread, laneClass }) => {
      render(
        <ActivityRow
          item={item({ isUnread })}
          menu={taskMenu()}
          onMarkRead={vi.fn()}
          onActivate={vi.fn()}
          blockedTaskIds={NO_BLOCKED_TASKS}
          compact
        />,
      );

      const row = screen.getByText("Say hello").closest("button");
      expect(row).toHaveClass("py-1.5", laneClass);
      expect(
        screen.getByLabelText("Options for Say hello"),
      ).toBeInTheDocument();
    },
  );

  it("offers the row's task actions from its options menu", async () => {
    // Real timers: the menu's open transition and `waitFor` both need a clock.
    vi.useRealTimers();
    const onArchive = vi.fn();
    render(
      <ActivityRow
        item={item({})}
        menu={taskMenu({ onArchive })}
        onMarkRead={vi.fn()}
        onActivate={vi.fn()}
        blockedTaskIds={NO_BLOCKED_TASKS}
      />,
    );

    fireEvent.mouseDown(screen.getByLabelText("Options for Say hello"), {
      button: 0,
    });

    await waitFor(() =>
      expect(screen.getByText("Archive")).toBeInTheDocument(),
    );
    for (const label of [
      "Open in new tab",
      "Pin",
      "Add to Command Center…",
      "File to…",
      "Archive",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    // A rename edits the row in place, and the feed has no inline editor.
    expect(screen.queryByText("Rename")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Archive"));
    expect(onArchive).toHaveBeenCalledOnce();
  });

  it("opens an activity mention at its exact comment thread", () => {
    const activity = item({
      activityKind: "mention",
      channelId: "channel-1",
      commentId: "comment-1",
      commentTarget: { scope: "desktop_canvas", itemId: "canvas-1" },
      author: {
        id: 2,
        uuid: "author",
        email: "author@posthog.com",
        first_name: "Ann",
      },
    });

    render(
      <ActivityRow
        item={activity}
        menu={taskMenu()}
        onMarkRead={vi.fn()}
        onActivate={openActivityItem}
        blockedTaskIds={NO_BLOCKED_TASKS}
      />,
    );
    const activityButton = screen
      .getByText("just now · Ann mentioned you")
      .closest("button");
    if (!activityButton) throw new Error("Expected activity row button");
    fireEvent.click(activityButton);

    expect(navigation.toChannelDashboard).toHaveBeenCalledWith(
      "channel-1",
      "canvas-1",
    );
    expect(navigation.toChannelTask).not.toHaveBeenCalled();
    expect(useCommentNavigationStore.getState().focusByTask["task-1"]).toEqual({
      target: { scope: "desktop_canvas", itemId: "canvas-1" },
      threadId: "comment-1",
      nonce: expect.any(Number),
      openCommentsTab: true,
      intent: "navigate",
    });
  });
});
