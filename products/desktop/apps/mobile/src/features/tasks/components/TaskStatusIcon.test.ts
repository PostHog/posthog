import type { Task } from "@posthog/shared";
import { describe, expect, it } from "vitest";
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
  it.each([
    ["pr_url only", { pr_url: "https://github.com/PostHog/code/pull/1" }],
    ["pr_urls only", { pr_urls: ["https://github.com/PostHog/code/pull/2"] }],
    [
      "both fields",
      {
        pr_url: "https://github.com/PostHog/code/pull/1",
        pr_urls: ["https://github.com/PostHog/code/pull/2"],
      },
    ],
  ])("prioritizes PR over cloud status (%s)", (_label, output) => {
    const task = makeTask({
      environment: "cloud",
      status: "in_progress",
      output,
    });

    expect(getTaskStatusIconKind(task)).toBe("pr");
  });

  it.each([
    ["output has no PR fields", { commit: "abc123" }],
    ["pr_urls is empty", { pr_urls: [] }],
    ["pr_url is an empty string", { pr_url: "" }],
  ])("does not return pr when %s", (_label, output) => {
    expect(
      getTaskStatusIconKind(
        makeTask({ environment: "cloud", status: "in_progress", output }),
      ),
    ).toBe("chat");
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
