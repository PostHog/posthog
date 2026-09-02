import type { TaskMention, UserBasic } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  countUnseenActivity,
  mergeTaskMentions,
  toMentionActivityItems,
} from "./mentionActivity";

const ann: UserBasic = {
  id: 2,
  uuid: "ann-uuid",
  email: "ann@posthog.com",
  first_name: "Ann",
};

function mention(overrides: Partial<TaskMention> = {}): TaskMention {
  return {
    id: "mention-1",
    message_id: "m1",
    task_id: "t1",
    task_title: "Task t1",
    channel_id: "c1",
    channel_name: "general",
    author: ann,
    content: "ping @[Me](me@posthog.com)",
    created_at: "2026-07-01T10:00:00Z",
    ...overrides,
  };
}

describe("toMentionActivityItems", () => {
  it("maps mention DTOs to feed items", () => {
    expect(toMentionActivityItems([mention()])).toEqual([
      {
        messageId: "m1",
        taskId: "t1",
        taskTitle: "Task t1",
        channelId: "c1",
        channelName: "general",
        author: ann,
        content: "ping @[Me](me@posthog.com)",
        createdAt: "2026-07-01T10:00:00Z",
      },
    ]);
  });

  it("labels untitled tasks and tolerates missing channel and author", () => {
    const items = toMentionActivityItems([
      mention({
        task_title: "",
        channel_id: null,
        channel_name: null,
        author: null,
      }),
    ]);
    expect(items[0]).toMatchObject({
      taskTitle: "Untitled task",
      channelId: null,
      channelName: null,
      author: null,
    });
  });
});

describe("countUnseenActivity", () => {
  const items = toMentionActivityItems([
    mention({ message_id: "m2", created_at: "2026-07-03T10:00:00Z" }),
    mention({ message_id: "m1", created_at: "2026-07-01T10:00:00Z" }),
  ]);

  it("counts everything when never seen", () => {
    expect(countUnseenActivity(items, null)).toBe(2);
  });

  it("counts only items after the last-seen timestamp", () => {
    expect(countUnseenActivity(items, "2026-07-02T00:00:00Z")).toBe(1);
    expect(countUnseenActivity(items, "2026-07-04T00:00:00Z")).toBe(0);
  });
});

describe("mergeTaskMentions", () => {
  it("prepends newly-fetched mentions ahead of the previous page", () => {
    const previous = [
      mention({ message_id: "m1", created_at: "2026-07-01T10:00:00Z" }),
    ];
    const incoming = [
      mention({ message_id: "m2", created_at: "2026-07-02T10:00:00Z" }),
    ];
    expect(
      mergeTaskMentions(previous, incoming).map((m) => m.message_id),
    ).toEqual(["m2", "m1"]);
  });

  it("replaces a mention that was re-fetched instead of duplicating it", () => {
    const previous = [
      mention({
        message_id: "m1",
        content: "old",
        created_at: "2026-07-01T10:00:00Z",
      }),
    ];
    const incoming = [
      mention({
        message_id: "m1",
        content: "edited",
        created_at: "2026-07-01T10:00:00Z",
      }),
    ];
    const merged = mergeTaskMentions(previous, incoming);
    expect(merged).toHaveLength(1);
    expect(merged[0].content).toBe("edited");
  });

  it("returns the previous page unchanged when there is nothing new", () => {
    const previous = [
      mention({ message_id: "m1", created_at: "2026-07-01T10:00:00Z" }),
    ];
    expect(mergeTaskMentions(previous, [])).toEqual(previous);
  });

  it("caps the merged result so a long session can't grow it unbounded", () => {
    const previous = Array.from({ length: 300 }, (_, i) =>
      mention({
        message_id: `old-${i}`,
        created_at: `2026-06-01T${String(i % 24).padStart(2, "0")}:00:00Z`,
      }),
    );
    const incoming = [
      mention({ message_id: "newest", created_at: "2026-07-05T10:00:00Z" }),
    ];
    const merged = mergeTaskMentions(previous, incoming);
    expect(merged).toHaveLength(300);
    expect(merged[0].message_id).toBe("newest");
  });
});
