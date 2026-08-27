import {
  type ChannelScopedTask,
  countSessionsByChannel,
  latestActivityForChannel,
  unreadChannelIds,
} from "@posthog/core/canvas/channelUnread";
import type { MentionActivityItem } from "@posthog/core/canvas/mentionActivity";
import { describe, expect, it } from "vitest";

function mention(
  overrides: Partial<MentionActivityItem> & { createdAt: string },
): MentionActivityItem {
  return {
    messageId: `m-${overrides.createdAt}`,
    taskId: "t1",
    taskTitle: "Task",
    channelId: "c1",
    channelName: "mobile",
    author: null,
    content: "hey @adam",
    ...overrides,
  };
}

describe("unreadChannelIds", () => {
  const cases: {
    name: string;
    lastSeen: Record<string, string>;
    expected: string[];
  }[] = [
    {
      name: "a channel never seen is unread",
      lastSeen: {},
      expected: ["c1"],
    },
    {
      name: "activity newer than the last visit is unread",
      lastSeen: { c1: "2026-07-16T09:00:00.000Z" },
      expected: ["c1"],
    },
    {
      name: "activity older than the last visit is read",
      lastSeen: { c1: "2026-07-16T11:00:00.000Z" },
      expected: [],
    },
    {
      name: "activity exactly at the last visit is read",
      lastSeen: { c1: "2026-07-16T10:00:00.000Z" },
      expected: [],
    },
  ];
  it.each(cases)("$name", ({ lastSeen, expected }) => {
    const items = [mention({ createdAt: "2026-07-16T10:00:00.000Z" })];
    expect([...unreadChannelIds(items, lastSeen)]).toEqual(expected);
  });

  it("compares each channel against its own last visit", () => {
    const items = [
      mention({ channelId: "c1", createdAt: "2026-07-16T10:00:00.000Z" }),
      mention({ channelId: "c2", createdAt: "2026-07-16T10:00:00.000Z" }),
    ];
    const unread = unreadChannelIds(items, {
      c1: "2026-07-16T11:00:00.000Z",
      c2: "2026-07-16T09:00:00.000Z",
    });
    expect([...unread]).toEqual(["c2"]);
  });

  it("uses the newest item in a channel, whatever the order", () => {
    const items = [
      mention({ messageId: "old", createdAt: "2026-07-16T08:00:00.000Z" }),
      mention({ messageId: "new", createdAt: "2026-07-16T12:00:00.000Z" }),
    ];
    expect([
      ...unreadChannelIds(items, { c1: "2026-07-16T10:00:00.000Z" }),
    ]).toEqual(["c1"]);
  });

  it("ignores channel-less mentions", () => {
    const items = [
      mention({ channelId: null, createdAt: "2026-07-16T10:00Z" }),
    ];
    expect([...unreadChannelIds(items, {})]).toEqual([]);
  });
});

describe("countSessionsByChannel", () => {
  const counted = new Set(["a", "b", "unfiled"]);
  const tasks: ChannelScopedTask[] = [
    { id: "a", channel: "c1" },
    { id: "b", channel: "c1" },
    { id: "quiet", channel: "c1" },
    { id: "unfiled", channel: null },
    { id: "other", channel: "c2" },
  ];

  it("counts a channel's sessions and leaves out the ones that don't count", () => {
    const byChannel = countSessionsByChannel(tasks, (t) => counted.has(t.id));
    expect(byChannel.get("c1")).toBe(2);
  });

  // A zero would render an empty dot slot; the row has to be able to ask "is
  // there anything here" and get nothing back.
  it("leaves a channel with nothing counted out of the map entirely", () => {
    const byChannel = countSessionsByChannel(tasks, (t) => counted.has(t.id));
    expect(byChannel.has("c2")).toBe(false);
  });

  it("skips sessions filed nowhere, however they count", () => {
    const byChannel = countSessionsByChannel(tasks, () => true);
    expect([...byChannel]).toEqual([
      ["c1", 3],
      ["c2", 1],
    ]);
  });
});

describe("latestActivityForChannel", () => {
  it("returns the newest timestamp for that channel only", () => {
    const items = [
      mention({ channelId: "c1", createdAt: "2026-07-16T08:00:00.000Z" }),
      mention({ channelId: "c1", createdAt: "2026-07-16T12:00:00.000Z" }),
      mention({ channelId: "c2", createdAt: "2026-07-16T13:00:00.000Z" }),
    ];
    expect(latestActivityForChannel(items, "c1")).toBe(
      "2026-07-16T12:00:00.000Z",
    );
  });

  it("is undefined for a channel with no activity, or no channel", () => {
    expect(latestActivityForChannel([], "c1")).toBeUndefined();
    expect(latestActivityForChannel([], undefined)).toBeUndefined();
  });
});
