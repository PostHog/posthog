import type { ActivityRow } from "@posthog/core/canvas/activityTimeline";
import {
  CANVAS_TASK_ACTIVITY_MAX_LIMIT,
  toCanvasTaskActivity,
} from "@posthog/core/canvas/canvasTaskActivity";
import { describe, expect, it } from "vitest";

const task = {
  id: "task-1",
  title: "Fix the login redirect",
  status: "completed",
  createdAt: "2026-08-01T10:00:00.000Z",
  updatedAt: "2026-08-01T12:00:00.000Z",
};

function eventRow(event: ActivityRow & { kind: "event" }): ActivityRow {
  return event;
}

function message(id: string): {
  id: string;
  content: string;
  created_at: string;
} {
  return { id, content: "hello", created_at: "2026-08-01T10:05:00.000Z" };
}

describe("toCanvasTaskActivity", () => {
  it.each([
    [
      "a pull request row carries the url the canvas links to",
      eventRow({
        kind: "event",
        key: "event-1",
        ts: Date.parse("2026-08-01T11:00:00.000Z"),
        event: {
          kind: "pr_created",
          payload: {
            prUrl: "https://github.com/PostHog/posthog/pull/12",
            repository: "PostHog/posthog",
            prNumber: 12,
            actor: null,
          },
        },
        message: message("m1"),
      }),
      {
        title: "Opened PostHog/posthog#12",
        url: "https://github.com/PostHog/posthog/pull/12",
      },
    ],
    [
      "a push row counts the commits the push carried, not the ones it listed",
      eventRow({
        kind: "event",
        key: "event-2",
        ts: Date.parse("2026-08-01T11:05:00.000Z"),
        event: {
          kind: "commits_pushed",
          payload: {
            runId: "run-1",
            branch: "main",
            repository: null,
            commits: [{ sha: "abc", subject: "Fix it", url: null }],
            total: 4,
          },
        },
        message: message("m2"),
      }),
      { title: "Pushed 4 commits to main", url: null },
    ],
    [
      "a failed run carries its summary as the detail",
      eventRow({
        kind: "event",
        key: "event-3",
        ts: Date.parse("2026-08-01T11:10:00.000Z"),
        event: {
          kind: "run_failed",
          payload: { runId: "run-1", errorSummary: "Tests failed" },
        },
        message: message("m3"),
      }),
      { title: "Run failed", url: null },
    ],
  ])("%s", (_name, row, expected) => {
    const [line] = toCanvasTaskActivity({ task, rows: [row] }).rows;
    expect(line).toMatchObject(expected);
  });

  it("keeps the newest rows when the timeline is longer than the limit", () => {
    const rows: ActivityRow[] = Array.from({ length: 5 }, (_, index) => ({
      kind: "task_created",
      key: `row-${index}`,
      ts: Date.parse("2026-08-01T10:00:00.000Z") + index,
    }));

    const snapshot = toCanvasTaskActivity({ task, rows, limit: 2 });

    expect(snapshot.rows.map((row) => row.key)).toEqual(["row-3", "row-4"]);
    expect(snapshot.truncated).toBe(true);
  });

  it("holds the limit a canvas asks for inside the bridge's bound", () => {
    const rows: ActivityRow[] = Array.from(
      { length: CANVAS_TASK_ACTIVITY_MAX_LIMIT + 10 },
      (_, index) => ({
        kind: "task_created",
        key: `row-${index}`,
        ts: Date.parse("2026-08-01T10:00:00.000Z") + index,
      }),
    );

    const snapshot = toCanvasTaskActivity({ task, rows, limit: 10_000 });

    expect(snapshot.rows).toHaveLength(CANVAS_TASK_ACTIVITY_MAX_LIMIT);
  });
});
