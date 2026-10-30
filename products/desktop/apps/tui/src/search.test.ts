import type { Task } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { editQuery, searchRows } from "./search";

describe("editQuery", () => {
  it.each([
    ["adds a typed character", "fi", "x", "fix"],
    ["adds a kitty-encoded character", "fi", "\x1b[120u", "fix"],
    ["takes the last character on Backspace", "fix", "\x7f", "fi"],
    ["adds a paste as one line", "", "\x1b[200~fix\nit\x1b[201~", "fix it"],
    ["ignores a navigation key", "fix", "\x1b[C", "fix"],
  ])("%s", (_, query, sequence, expected) => {
    expect(editQuery(query, sequence)).toBe(expected);
  });
});

describe("searchRows", () => {
  it("gives each task the sidebar's status and when it was last active", () => {
    const hoursAgo = (hours: number): string =>
      new Date(Date.now() - hours * 3_600_000).toISOString();
    const tasks = [
      {
        id: "cloud",
        title: "Cloud",
        last_activity_at: hoursAgo(2),
        latest_run: { status: "failed", state: {} },
      },
      { id: "busy", title: "Busy", last_activity_at: hoursAgo(50) },
      { id: "here", title: "Here" },
    ] as Task[];

    const rows = searchRows(tasks, {
      working: new Set(["busy"]),
      waiting: new Set(),
      local: {
        active: new Map([["here", Date.now() - 5 * 60_000]]),
        running: new Set(["here"]),
      },
    });

    expect(rows).toEqual([
      {
        taskId: "cloud",
        title: "Cloud",
        indicator: "failed",
        local: false,
        age: "2h ago",
      },
      {
        taskId: "busy",
        title: "Busy",
        indicator: "working",
        local: false,
        age: "2d ago",
      },
      {
        taskId: "here",
        title: "Here",
        indicator: "alive",
        local: true,
        age: "5m ago",
      },
    ]);
  });
});
