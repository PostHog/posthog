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
import { ActivityRow } from "./ActivityView";
import { activityMetadata } from "./activityMetadata";
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

describe("activityMetadata", () => {
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
  it.each([
    [
      "completed run",
      item({ activityKind: "completed" }),
      "Agent completed · now",
    ],
    ["agent reply", item({ activityKind: "message" }), "Agent replied · now"],
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
      "Ann replied to a thread you participated in · now",
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
      "Ann commented on your canvas · now",
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
      "You replied · now",
    ],
  ])("labels a %s", (_name, activity, expected) => {
    expect(activityMetadata(activity, "me@posthog.com")).toBe(expected);
  });

  it.each([
    ["shared channel", "engineering", "Agent completed · #engineering · now"],
    ["personal channel", "personal", "Agent completed · Personal · now"],
  ])("formats the %s label", (_name, channelName, expected) => {
    expect(
      activityMetadata(
        item({ activityKind: "completed", channelName }),
        "me@posthog.com",
      ),
    ).toBe(expected);
  });

  it("leads a completed activity row with the task title", () => {
    render(
      <ActivityRow
        item={item({
          activityKind: "completed",
          taskTitle: "Tell me a joke",
          channelName: "personal",
        })}
        channelId="channel-1"
        onOpen={vi.fn()}
        onMarkRead={vi.fn()}
        onActivate={vi.fn()}
        blockedTaskIds={NO_BLOCKED_TASKS}
        compact
      />,
    );

    const title = screen.getByText("Tell me a joke");
    const metadata = screen.getByText("Agent completed · Personal · now");
    expect(title.compareDocumentPosition(metadata)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
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
        onActivate={openActivityItem}
        blockedTaskIds={NO_BLOCKED_TASKS}
      />,
    );
    const activityButton = screen
      .getByText("Ann mentioned you · now")
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
