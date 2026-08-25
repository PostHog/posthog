import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  type AgentActivityIconKind,
  activityPresentation,
} from "./activityPresentation";

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

const AUTHOR = {
  id: 2,
  uuid: "author",
  email: "author@posthog.com",
  first_name: "Ann",
};

describe("activityPresentation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-27T10:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each<[string, TaskActivityItem, string, AgentActivityIconKind | null]>([
    [
      "completed run",
      item({
        activityKind: "completed",
        activityAt: "2026-07-26T16:00:00Z",
      }),
      "18h ago · Agent completed",
      "check",
    ],
    [
      "waiting agent",
      item({ activityKind: "awaiting_input" }),
      "just now · Agent is waiting for your reply",
      "question",
    ],
    [
      "agent reply",
      item({ activityKind: "message" }),
      "just now · Agent replied",
      "chat",
    ],
    [
      "another person's reply",
      item({ activityKind: "message", author: AUTHOR }),
      "just now · Ann replied",
      null,
    ],
    [
      "mention",
      item({ activityKind: "mention", author: AUTHOR }),
      "just now · Ann mentioned you",
      null,
    ],
    [
      "thread reply",
      item({ activityKind: "thread_reply", author: AUTHOR }),
      "just now · Ann replied to a thread you participated in",
      null,
    ],
    [
      "canvas owner comment",
      item({
        activityKind: "owned_item_comment",
        commentTarget: { scope: "desktop_canvas", itemId: "canvas-1" },
        author: AUTHOR,
      }),
      "just now · Ann commented on your canvas",
      null,
    ],
    [
      "created task",
      item({ activityKind: "created" }),
      "just now · You created",
      null,
    ],
  ])("presents a %s", (_name, activity, metadata, agentIcon) => {
    expect(activityPresentation(activity, "me@posthog.com")).toEqual({
      metadata,
      agentIcon,
    });
  });

  it.each([
    [
      "shared channel",
      "engineering",
      "just now · Agent completed · #engineering",
    ],
    ["personal channel", "personal", "just now · Agent completed · Personal"],
  ])("formats the %s label", (_name, channelName, metadata) => {
    expect(
      activityPresentation(
        item({ activityKind: "completed", channelName }),
        "me@posthog.com",
      ).metadata,
    ).toBe(metadata);
  });
});
