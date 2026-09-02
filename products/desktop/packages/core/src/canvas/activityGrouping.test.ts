import { parseActivityEvent } from "@posthog/core/canvas/activityEvents";
import { groupActivityRows } from "@posthog/core/canvas/activityGrouping";
import type { ActivityRow } from "@posthog/core/canvas/activityTimeline";
import type { ThreadMessageLike } from "@posthog/core/canvas/threadTimeline";
import { describe, expect, it } from "vitest";

let nextId = 0;

// Each fixture row is one tick newer than the last, which is all the order the grouping reads.
function eventRow(
  event: string,
  payload: Record<string, unknown>,
): ActivityRow {
  nextId += 1;
  const ts = nextId;
  const message: ThreadMessageLike = {
    id: `m${nextId}`,
    content: "",
    created_at: new Date(ts).toISOString(),
    author_kind: "agent",
    event,
    payload,
  };
  const parsed = parseActivityEvent(message);
  if (!parsed) throw new Error(`unparsed fixture event: ${event}`);
  return {
    kind: "event",
    key: `event-${message.id}`,
    ts,
    event: parsed,
    message,
  };
}

function push(branch: string, ...shas: string[]): ActivityRow {
  return eventRow("commits_pushed", {
    run_id: "run-1",
    branch,
    repository: "PostHog/posthog",
    commits: shas.map((sha) => ({ sha, subject: `work ${sha}` })),
    total: shas.length,
  });
}

function pr(number: number): ActivityRow {
  return eventRow("pr_created", {
    pr_url: `https://github.com/PostHog/posthog/pull/${number}`,
  });
}

const prompt: ActivityRow = {
  kind: "user_message",
  key: "user-message-1",
  ts: 0,
  item: { id: "1", content: "go", timestamp: 0 },
};

describe("activity grouping", () => {
  it("collapses repeated pushes to one branch into one row", () => {
    const grouped = groupActivityRows([
      push("main", "aaa"),
      push("main", "bbb"),
      push("main", "ccc", "ddd"),
    ]);

    expect(grouped).toHaveLength(1);
    const [row] = grouped;
    if (row?.kind !== "event_group") throw new Error("expected a group");
    expect(row.events).toHaveLength(3);
    // The newest member's, so the row reads as when the stretch of pushes ended.
    expect(row.ts).toBe(3);
  });

  it.each([
    [
      "one of each kind stays one row each",
      () => [push("main", "aaa"), pr(1)],
      ["event", "event"],
    ],
    [
      "two branches stay two rows",
      () => [
        push("main", "aaa"),
        push("side", "bbb"),
        push("main", "ccc"),
        push("side", "ddd"),
      ],
      ["event_group", "event_group"],
    ],
    [
      "a pull request between pushes doesn't split them",
      () => [push("main", "aaa"), pr(1), push("main", "bbb"), pr(2)],
      ["event_group", "event_group"],
    ],
    [
      "a prompt between pushes does",
      () => [push("main", "aaa"), prompt, push("main", "bbb")],
      ["event", "user_message", "event"],
    ],
  ])("%s", (_name, rows, expected) => {
    expect(groupActivityRows(rows()).map((row) => row.kind)).toEqual(expected);
  });
});
