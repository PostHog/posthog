import { describe, expect, it } from "vitest";
import type { Task } from "../types";
import { getTaskStatusIconKind } from "./taskStatusIconKind";

function makeTask(latestRun?: Partial<NonNullable<Task["latest_run"]>>): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Test task",
    description: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    origin_product: "code",
    latest_run: latestRun
      ? {
          id: "run-1",
          task: "task-1",
          team: 1,
          branch: null,
          stage: null,
          environment: "local",
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

describe("getTaskStatusIconKind", () => {
  it("prioritizes PR over cloud status", () => {
    const task = makeTask({
      environment: "cloud",
      status: "in_progress",
      output: { pr_url: "https://github.com/PostHog/code/pull/123" },
    });

    expect(getTaskStatusIconKind(task)).toBe("pr");
  });

  it("shows chat for cloud tasks without a PR, regardless of run status", () => {
    expect(
      getTaskStatusIconKind(
        makeTask({ environment: "cloud", status: "queued" }),
      ),
    ).toBe("chat");

    expect(
      getTaskStatusIconKind(
        makeTask({ environment: "cloud", status: "in_progress" }),
      ),
    ).toBe("chat");

    expect(
      getTaskStatusIconKind(
        makeTask({ environment: "cloud", status: "started" }),
      ),
    ).toBe("chat");

    expect(
      getTaskStatusIconKind(
        makeTask({ environment: "cloud", status: "completed" }),
      ),
    ).toBe("chat");

    expect(
      getTaskStatusIconKind(
        makeTask({ environment: "cloud", status: "cancelled" }),
      ),
    ).toBe("chat");
  });

  it("preserves local run-state icons", () => {
    expect(
      getTaskStatusIconKind(
        makeTask({ environment: "local", status: "in_progress" }),
      ),
    ).toBe("running");

    expect(
      getTaskStatusIconKind(
        makeTask({ environment: "local", status: "failed" }),
      ),
    ).toBe("failed");
  });

  it("falls back to chat when a task has no run yet", () => {
    expect(getTaskStatusIconKind(makeTask())).toBe("chat");
  });
});
