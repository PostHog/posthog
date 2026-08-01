import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { activityHeadline } from "./ActivityView";

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

describe("activityHeadline", () => {
  it.each([
    [
      "completed run",
      item({ activityKind: "completed" }),
      "The agent completed this task",
    ],
    ["agent reply", item({ activityKind: "message" }), "The agent replied"],
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

  it("prefixes channel names with a hash", () => {
    const { getByText } = render(
      <div>
        {activityHeadline(
          item({ activityKind: "completed", channelName: "me" }),
          "me@posthog.com",
        )}
      </div>,
    );
    expect(getByText("#me")).toBeInTheDocument();
  });
});
