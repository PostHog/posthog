import type { Task, TaskRun } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { getTaskStatusPresentationKind } from "./taskStatusPresentation";

function makeTask(latestRun?: Partial<TaskRun>): Pick<Task, "latest_run"> {
  return {
    latest_run: latestRun
      ? {
          id: "run-1",
          task: "task-1",
          team: 1,
          branch: null,
          status: "not_started",
          log_url: "",
          error_message: null,
          output: null,
          state: {},
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          completed_at: null,
          ...latestRun,
        }
      : undefined,
  };
}

describe("getTaskStatusPresentationKind", () => {
  it("prioritizes a pull request over cloud presentation", () => {
    expect(
      getTaskStatusPresentationKind(
        makeTask({
          environment: "cloud",
          status: "in_progress",
          output: { pr_url: "https://github.com/PostHog/code/pull/123" },
        }),
      ),
    ).toBe("pr");
  });

  it.each([
    "not_started",
    "queued",
    "in_progress",
    "completed",
    "failed",
    "cancelled",
  ] as const)("uses chat presentation for cloud status %s", (status) => {
    expect(
      getTaskStatusPresentationKind(makeTask({ environment: "cloud", status })),
    ).toBe("chat");
  });

  it.each([
    ["completed", "completed"],
    ["failed", "failed"],
    ["in_progress", "running"],
    ["queued", "started"],
    ["not_started", "chat"],
    ["cancelled", "chat"],
  ] as const)("maps local status %s to %s", (status, expected) => {
    expect(
      getTaskStatusPresentationKind(makeTask({ environment: "local", status })),
    ).toBe(expected);
  });

  it("falls back to chat when a task has no run", () => {
    expect(getTaskStatusPresentationKind(makeTask())).toBe("chat");
  });
});
