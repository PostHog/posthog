import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
import { ActivityRow } from "./ActivityView";
import { activityHeadline } from "./activityHeadline";

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

describe("activityHeadline", () => {
  beforeEach(() => {
    navigation.toChannelTask.mockReset();
    navigation.toChannelDashboard.mockReset();
    navigation.toTaskDetail.mockReset();
    useCommentNavigationStore.setState({
      focusByTask: {},
      resolutionsByTarget: {},
    });
  });
  it.each([
    [
      "completed run",
      item({ activityKind: "completed" }),
      "The agent completed this task",
    ],
    ["agent reply", item({ activityKind: "message" }), "The agent replied"],
    [
      "thread reply",
      item({
        activityKind: "thread_reply",
        author: {
          id: 2,
          uuid: "author",
          email: "author@posthog.com",
          first_name: "Ann",
        },
      }),
      "replied to a thread you participated in",
    ],
    [
      "canvas owner comment",
      item({
        activityKind: "owned_item_comment",
        commentTarget: { scope: "desktop_canvas", itemId: "canvas-1" },
        author: {
          id: 2,
          uuid: "author",
          email: "author@posthog.com",
          first_name: "Ann",
        },
      }),
      "commented on your canvas",
    ],
    [
      "own reply",
      item({
        activityKind: "message",
        author: {
          id: 1,
          uuid: "me",
          email: "me@posthog.com",
          first_name: "Me",
        },
      }),
      "You replied",
    ],
  ])("labels a %s", (_name, activity, expected) => {
    const { getByText } = render(
      <div>{activityHeadline(activity, "me@posthog.com")}</div>,
    );
    expect(getByText(expected)).toBeInTheDocument();
  });

  it.each([
    ["shared channel", "engineering", "#engineering"],
    ["personal channel", "personal", "your personal space"],
  ])("formats the %s label", (_name, channelName, expected) => {
    const { getByText } = render(
      <div>
        {activityHeadline(
          item({ activityKind: "completed", channelName }),
          "me@posthog.com",
        )}
      </div>,
    );
    expect(getByText(expected)).toBeInTheDocument();
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
        channelId="channel-1"
        onOpen={vi.fn()}
        onMarkRead={vi.fn()}
        blockedTaskIds={NO_BLOCKED_TASKS}
      />,
    );
    const activityButton = screen.getByText("mentioned you").closest("button");
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
