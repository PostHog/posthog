import {
  liveUuidsFromTasks,
  PRESENCE_LIVE_WINDOW_MS,
  PRESENCE_RECENT_WINDOW_MS,
  presenceByChannel,
  presenceTier,
  shouldShowUserPresence,
} from "@posthog/core/canvas/presence";
import type { Task, UserBasic } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";

const NOW = 1_700_000_000_000;

function user(uuid: string): UserBasic {
  return { id: 1, uuid, email: `${uuid}@example.com` };
}

function task(
  createdBy: UserBasic | null,
  agoMs: number,
): Pick<Task, "created_by" | "last_activity_at"> {
  return {
    created_by: createdBy,
    last_activity_at: new Date(NOW - agoMs).toISOString(),
  };
}

describe("presenceTier", () => {
  it.each([
    ["just now", 0, "live"],
    ["inside the live window", PRESENCE_LIVE_WINDOW_MS - 1, "live"],
    ["at the live boundary", PRESENCE_LIVE_WINDOW_MS, "recent"],
    ["inside the recent window", PRESENCE_RECENT_WINDOW_MS - 1, "recent"],
    ["at the recent boundary", PRESENCE_RECENT_WINDOW_MS, "idle"],
    ["long ago", PRESENCE_RECENT_WINDOW_MS * 2, "idle"],
  ])("reads %s as %s", (_label, agoMs, expected) => {
    expect(presenceTier(NOW - agoMs, NOW)).toBe(expected);
  });

  it("treats a future timestamp (clock skew) as live", () => {
    expect(presenceTier(NOW + 60_000, NOW)).toBe("live");
  });
});

describe("shouldShowUserPresence", () => {
  it.each([
    {
      case: "the current user",
      userUuid: "a",
      currentUserUuid: "a",
      expected: false,
    },
    {
      case: "another user",
      userUuid: "a",
      currentUserUuid: "b",
      expected: true,
    },
    {
      case: "an unknown current user",
      userUuid: "a",
      currentUserUuid: undefined,
      expected: false,
    },
    {
      case: "an unknown presence user",
      userUuid: undefined,
      currentUserUuid: "b",
      expected: false,
    },
  ])(
    "returns $expected for $case",
    ({ userUuid, currentUserUuid, expected }) => {
      expect(shouldShowUserPresence(userUuid, currentUserUuid)).toBe(expected);
    },
  );
});

describe("liveUuidsFromTasks", () => {
  it("includes only authors active within the live window", () => {
    const live = liveUuidsFromTasks(
      [
        task(user("a"), 60_000), // live
        task(user("b"), PRESENCE_LIVE_WINDOW_MS + 60_000), // recent, not live
        task(user("c"), PRESENCE_RECENT_WINDOW_MS + 60_000), // idle
      ],
      NOW,
    );
    expect([...live].sort()).toEqual(["a"]);
  });

  it("marks a person live from their most recent task, ignoring older ones", () => {
    const live = liveUuidsFromTasks(
      [task(user("a"), PRESENCE_LIVE_WINDOW_MS * 5), task(user("a"), 30_000)],
      NOW,
    );
    expect(live.has("a")).toBe(true);
  });

  it("skips tasks with no author or an unparseable timestamp", () => {
    const live = liveUuidsFromTasks(
      [
        task(null, 0),
        { created_by: user("a"), last_activity_at: "not-a-date" },
        { created_by: user("b"), last_activity_at: undefined },
      ],
      NOW,
    );
    expect(live.size).toBe(0);
  });
});

describe("presenceByChannel", () => {
  function chanTask(
    channel: string | null,
    createdBy: UserBasic | null,
    agoMs: number,
  ): Pick<Task, "created_by" | "last_activity_at" | "channel"> {
    return {
      channel,
      created_by: createdBy,
      last_activity_at: new Date(NOW - agoMs).toISOString(),
    };
  }

  it("groups recently-active people by channel, most-recent first", () => {
    const map = presenceByChannel(
      [
        chanTask("c1", user("a"), 30_000), // most recent in c1
        chanTask("c1", user("b"), 90_000),
        chanTask("c2", user("c"), 60_000),
        chanTask("c1", user("d"), PRESENCE_RECENT_WINDOW_MS + 1), // idle, dropped
      ],
      { now: NOW, limit: 5, currentUserUuid: "viewer" },
    );
    expect(map.get("c1")?.people.map((p) => p.uuid)).toEqual(["a", "b"]);
    expect(map.get("c2")?.people.map((p) => p.uuid)).toEqual(["c"]);
  });

  it("marks only the live people, and only ones it kept", () => {
    const map = presenceByChannel(
      [
        chanTask("c1", user("a"), 30_000), // live
        chanTask("c1", user("b"), PRESENCE_LIVE_WINDOW_MS + 60_000), // recent
      ],
      { now: NOW, limit: 5, currentUserUuid: "viewer" },
    );
    expect([...(map.get("c1")?.liveUuids ?? [])]).toEqual(["a"]);
  });

  it("dedupes a person across their tasks and caps at the limit", () => {
    const map = presenceByChannel(
      [
        chanTask("c1", user("a"), 10_000),
        chanTask("c1", user("a"), 20_000),
        chanTask("c1", user("b"), 30_000),
        chanTask("c1", user("c"), 40_000),
      ],
      { now: NOW, limit: 2, currentUserUuid: "viewer" },
    );
    expect(map.get("c1")?.people.map((p) => p.uuid)).toEqual(["a", "b"]);
  });

  it("skips tasks with no channel", () => {
    const map = presenceByChannel([chanTask(null, user("a"), 0)], {
      now: NOW,
      limit: 5,
      currentUserUuid: "viewer",
    });
    expect(map.size).toBe(0);
  });

  it("excludes the current user", () => {
    const map = presenceByChannel(
      [chanTask("c1", user("a"), 30_000), chanTask("c1", user("b"), 60_000)],
      { now: NOW, limit: 5, currentUserUuid: "a" },
    );
    expect(map.get("c1")?.people.map((person) => person.uuid)).toEqual(["b"]);
  });
});
