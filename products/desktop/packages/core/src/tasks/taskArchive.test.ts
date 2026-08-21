import type { Task, TaskRunStatus } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { isTaskRunning } from "./taskArchive";

function makeTask(status?: TaskRunStatus): Pick<Task, "latest_run"> {
  return {
    latest_run: status
      ? {
          id: "run-1",
          task: "task-1",
          team: 1,
          branch: null,
          status,
          log_url: "",
          error_message: null,
          output: null,
          state: {},
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          completed_at: null,
        }
      : undefined,
  };
}

describe("isTaskRunning", () => {
  it("returns false when a task has no run", () => {
    expect(isTaskRunning(makeTask())).toBe(false);
  });

  it.each(["not_started", "queued", "in_progress"] as const)(
    "returns true for %s",
    (status) => {
      expect(isTaskRunning(makeTask(status))).toBe(true);
    },
  );

  it("returns true for the legacy started status", () => {
    expect(isTaskRunning({ latest_run: { status: "started" } })).toBe(true);
  });

  it.each(["completed", "failed", "cancelled"] as const)(
    "returns false for %s",
    (status) => {
      expect(isTaskRunning(makeTask(status))).toBe(false);
    },
  );
});
