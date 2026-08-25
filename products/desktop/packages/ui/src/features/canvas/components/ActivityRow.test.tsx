import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { fireEvent, render, screen } from "@testing-library/react";
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

import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { ActivityRow } from "./ActivityRow";
import { openActivityItem } from "./openActivityItem";

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
    const metadata = screen.getByText("just now · Agent completed · Personal");
    expect(title.compareDocumentPosition(metadata)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
    const row = title.closest("button");
    expect(row?.querySelector(".quill-avatar")).toHaveClass(
      "bg-primary",
      "text-primary-foreground",
    );
    expect(row).not.toHaveClass("bg-primary/10");
    expect(row).not.toHaveClass("outline-primary/20");
    expect(screen.queryByTitle("New activity")).not.toBeInTheDocument();
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
