import {
  liveUuidsFromTasks,
  PRESENCE_LIVE_WINDOW_MS,
  PRESENCE_RECENT_WINDOW_MS,
  presenceTier,
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
