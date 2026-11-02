import { ApiRequestError } from "@posthog/api-client/fetcher";
import type {
  SignalReportArtefactsResponse,
  Task,
} from "@posthog/shared/domain-types";
import { describe, expect, it, vi } from "vitest";
import {
  fetchHasLiveImplementationTask,
  implementationTaskIds,
  isLiveImplementationTask,
} from "./reportTasks";

function taskRun(taskId: string, type: string, product = "signals") {
  return {
    id: `artefact-${taskId}-${type}`,
    type: "task_run",
    created_at: "2026-01-01T00:00:00Z",
    content: { task_id: taskId, product, type },
  };
}

function artefacts(
  results: ReturnType<typeof taskRun>[],
): SignalReportArtefactsResponse {
  return {
    results,
    count: results.length,
  } as unknown as SignalReportArtefactsResponse;
}

function task(
  id: string,
  status: string | null,
  output: Record<string, unknown> | null = null,
): Task {
  return {
    id,
    latest_run: status === null ? undefined : { status, output },
  } as unknown as Task;
}

describe("implementationTaskIds", () => {
  it("keeps only signals implementation runs, once per task", () => {
    expect(
      implementationTaskIds(
        artefacts([
          taskRun("a", "implementation"),
          taskRun("a", "implementation"),
          taskRun("b", "research"),
          taskRun("c", "implementation", "custom"),
          taskRun("d", "implementation"),
        ]),
      ),
    ).toEqual(["a", "d"]);
  });
});

describe("isLiveImplementationTask", () => {
  it.each([
    ["a running run", task("t", "in_progress"), true],
    ["a failed run with no PR", task("t", "failed"), false],
    ["a task with no run", task("t", null), false],
    [
      "a finished run with an open PR",
      task("t", "completed", { pr_url: "https://github.com/o/r/pull/1" }),
      true,
    ],
    [
      "a merged PR",
      task("t", "completed", {
        pr_url: "https://github.com/o/r/pull/1",
        pr_state: "merged",
      }),
      false,
    ],
    [
      "a legacy merged PR",
      task("t", "completed", {
        pr_url: "https://github.com/o/r/pull/1",
        pr_merged: true,
      }),
      false,
    ],
  ])("%s", (_label, value, expected) => {
    expect(isLiveImplementationTask(value)).toBe(expected);
  });
});

describe("fetchHasLiveImplementationTask", () => {
  function client(tasks: Record<string, Task | Error>) {
    return {
      getSignalReportArtefacts: vi
        .fn()
        .mockResolvedValue(
          artefacts(
            Object.keys(tasks).map((id) => taskRun(id, "implementation")),
          ),
        ),
      getTask: vi.fn((id: string) => {
        const value = tasks[id];
        return value instanceof Error
          ? Promise.reject(value)
          : Promise.resolve(value);
      }),
    };
  }

  it("is true when one linked task is live", async () => {
    const c = client({
      a: task("a", "failed"),
      b: task("b", "in_progress"),
    });
    await expect(fetchHasLiveImplementationTask(c, "r")).resolves.toBe(true);
    expect(c.getSignalReportArtefacts).toHaveBeenCalledWith("r", {
      limit: 1000,
    });
  });

  it("skips a deleted task", async () => {
    const c = client({
      a: new ApiRequestError(404, "not found"),
      b: task("b", "completed"),
    });
    await expect(fetchHasLiveImplementationTask(c, "r")).resolves.toBe(false);
  });

  it("fails when a task lookup fails for another reason", async () => {
    const c = client({ a: new ApiRequestError(500, "boom") });
    await expect(fetchHasLiveImplementationTask(c, "r")).rejects.toThrow();
  });
});
