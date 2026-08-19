import type { TaskActivity, UserBasic } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { toTaskActivityItems } from "./taskActivity";

const ann: UserBasic = {
  id: 2,
  uuid: "ann-uuid",
  email: "ann@posthog.com",
  first_name: "Ann",
};

function activity(overrides: Partial<TaskActivity> = {}): TaskActivity {
  return {
    id: "activity-1",
    task_id: "t1",
    task_title: "Task t1",
    channel_id: "c1",
    channel_name: "general",
    activity_at: "2026-07-01T10:00:00Z",
    activity_kind: "mention",
    snippet: "ping @[Me](me@posthog.com)",
    latest_author: ann,
    latest_message_id: "m1",
    target_scope: null,
    target_id: null,
    is_unread: true,
    ...overrides,
  };
}

describe("toTaskActivityItems", () => {
  it("maps the authoritative activity and unread state", () => {
    expect(toTaskActivityItems([activity()])).toEqual([
      {
        id: "activity-1",
        taskId: "t1",
        taskTitle: "Task t1",
        channelId: "c1",
        channelName: "general",
        activityAt: "2026-07-01T10:00:00Z",
        activityKind: "mention",
        snippet: "ping @[Me](me@posthog.com)",
        author: ann,
        messageId: "m1",
        commentId: null,
        commentTarget: null,
        targetScope: null,
        targetId: null,
        isUnread: true,
      },
    ]);
  });

  it("maps a comment activity target for exact navigation", () => {
    const [item] = toTaskActivityItems([
      activity({
        latest_message_id: null,
        latest_comment_id: "comment-1",
        latest_comment_scope: "task_artifact",
        latest_comment_item_id: "artifact-1",
      }),
    ]);

    expect(item.commentId).toBe("comment-1");
    expect(item.commentTarget).toEqual({
      scope: "task_artifact",
      itemId: "artifact-1",
    });
  });

  it("maps a report canvas target for direct navigation", () => {
    const [item] = toTaskActivityItems([
      activity({ target_scope: "desktop_canvas", target_id: "canvas-1" }),
    ]);

    expect(item.targetScope).toBe("desktop_canvas");
    expect(item.targetId).toBe("canvas-1");
  });

  it("labels untitled tasks and tolerates missing optional values", () => {
    const [item] = toTaskActivityItems([
      activity({
        task_title: "",
        channel_id: null,
        channel_name: null,
        latest_author: null,
        latest_message_id: null,
        activity_kind: "created",
        snippet: "",
      }),
    ]);
    expect(item).toMatchObject({
      taskTitle: "Untitled task",
      channelId: null,
      channelName: null,
      author: null,
      messageId: null,
    });
  });
});
