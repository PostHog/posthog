import type { TaskActivity } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { feedChat, type InboxChat, inboxReason } from "./inbox";

const idle: InboxChat = {
  working: false,
  prompted: false,
  failed: false,
  turnEndedAt: 1_000,
  shells: 0,
  wake: false,
  repliedAt: 500,
  dismissedAt: null,
  readBefore: null,
};

describe("inboxReason", () => {
  it.each<[string, Partial<InboxChat>, ReturnType<typeof inboxReason>]>([
    ["a turn that ended after the last reply needs a reply", {}, "reply"],
    ["a reply since the turn ended clears it", { repliedAt: 1_000 }, null],
    [
      "a dismissal since the turn ended clears it",
      { dismissedAt: 1_500 },
      null,
    ],
    [
      "a turn ending after the dismissal brings it back",
      { dismissedAt: 900 },
      "reply",
    ],
    [
      "a turn that ended before everything was marked read is read",
      { readBefore: 1_000 },
      null,
    ],
    [
      "a turn that ended after that still needs a reply",
      { readBefore: 999 },
      "reply",
    ],
    ["a chat mid-turn is not done", { working: true }, null],
    [
      "a prompt needs an answer even mid-turn",
      { working: true, prompted: true },
      "prompt",
    ],
    [
      "a failed run needs attention",
      { failed: true, turnEndedAt: null },
      "failed",
    ],
    ["a background shell keeps the agent busy", { shells: 1 }, null],
    ["a scheduled wake-up keeps the agent busy", { wake: true }, null],
    [
      "a chat with no turn yet has nothing to answer",
      { turnEndedAt: null },
      null,
    ],
  ])("%s", (_name, chat, reason) => {
    expect(inboxReason({ ...idle, ...chat })).toBe(reason);
  });
});

describe("feedChat", () => {
  const row = (overrides: Partial<TaskActivity>): TaskActivity => ({
    id: "r",
    task_id: "t",
    task_title: "t",
    activity_at: "2026-11-03T01:00:00.000Z",
    activity_kind: "completed",
    snippet: "",
    is_unread: true,
    ...overrides,
  });

  it.each<[string, Partial<TaskActivity>, ReturnType<typeof inboxReason>]>([
    ["an unread finished turn needs a reply", {}, "reply"],
    ["a read one does not", { is_unread: false }, null],
    [
      "an unread question needs an answer",
      { activity_kind: "awaiting_input" },
      "prompt",
    ],
    [
      "a thread message is not a finished turn",
      { activity_kind: "message" },
      null,
    ],
  ])("%s", (_name, overrides, reason) => {
    const fed = feedChat(row(overrides), false, false, false);
    expect(
      fed &&
        inboxReason({
          ...idle,
          ...fed,
          repliedAt: null,
          turnEndedAt: fed.turnEndedAt,
        }),
    ).toBe(fed ? reason : null);
  });
});
