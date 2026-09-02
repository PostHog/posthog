import type { Task, TaskRunStatus } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { deriveCloudRunState } from "./cloudRunState";

function makeTask(runStatus: TaskRunStatus, runId = "run-1"): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Task",
    description: "",
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    origin_product: "user_created",
    latest_run: {
      id: runId,
      status: runStatus,
      environment: "cloud",
    } as Task["latest_run"],
  };
}

describe("deriveCloudRunState", () => {
  it("uses terminal task status over stale same-run session status", () => {
    const state = deriveCloudRunState(
      makeTask("completed"),
      {
        taskRunId: "run-1",
        cloudStatus: "in_progress",
      },
      null,
    );

    expect(state.cloudStatus).toBe("completed");
    expect(state.isRunActive).toBe(false);
  });

  it("uses task status when the session belongs to an older run", () => {
    const state = deriveCloudRunState(
      makeTask("in_progress", "new-run"),
      {
        taskRunId: "old-run",
        cloudStatus: "completed",
      },
      null,
    );

    expect(state.cloudStatus).toBe("in_progress");
    expect(state.isRunActive).toBe(true);
  });
});
