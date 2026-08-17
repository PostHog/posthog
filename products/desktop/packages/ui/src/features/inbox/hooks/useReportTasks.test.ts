import type { Task, TaskRun, TaskRunStatus } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  findContinuableImplementationTask,
  getTaskPrUrl,
  type ReportTaskData,
  type ReportTaskPurpose,
} from "./useReportTasks";

function makeTask(
  id: string,
  run?: { status?: TaskRunStatus; prUrl?: string | null },
): Task {
  const latest_run: TaskRun | undefined = run
    ? ({
        id: `${id}-run`,
        task: id,
        team: 1,
        branch: null,
        status: run.status ?? "in_progress",
        log_url: "",
        error_message: null,
        output: run.prUrl ? { pr_url: run.prUrl } : null,
        state: {},
        created_at: "2026-06-24T10:00:00Z",
        updated_at: "2026-06-24T10:00:00Z",
        completed_at: null,
      } as TaskRun)
    : undefined;
  return {
    id,
    task_number: null,
    slug: id,
    title: id,
    description: "",
    created_at: "2026-06-24T10:00:00Z",
    updated_at: "2026-06-24T10:00:00Z",
    origin_product: "signals",
    latest_run,
  } as Task;
}

function entry(
  task: Task,
  purpose: ReportTaskPurpose = "implementation",
): ReportTaskData {
  return { task, purpose, purposeLabel: purpose, startedAt: task.created_at };
}

describe("findContinuableImplementationTask", () => {
  it("returns null when there are no report tasks", () => {
    expect(findContinuableImplementationTask(undefined)).toBeNull();
    expect(findContinuableImplementationTask([])).toBeNull();
  });

  it("ignores research/other tasks", () => {
    const tasks = [
      entry(makeTask("r", { status: "in_progress" }), "research"),
      entry(makeTask("o", { prUrl: "https://gh/pr/1" }), "other"),
    ];
    expect(findContinuableImplementationTask(tasks)).toBeNull();
  });

  it("returns an implementation task that already has a PR", () => {
    const withPr = makeTask("impl", {
      status: "completed",
      prUrl: "https://gh/pr/9",
    });
    expect(findContinuableImplementationTask([entry(withPr)])).toBe(withPr);
  });

  it("returns a still-running implementation task with no PR yet", () => {
    const running = makeTask("impl", { status: "in_progress" });
    expect(findContinuableImplementationTask([entry(running)])).toBe(running);
  });

  it.each<TaskRunStatus>(["completed", "failed", "cancelled"])(
    "treats a terminal %s run with no PR as not continuable",
    (status) => {
      const terminal = makeTask("impl", { status });
      expect(findContinuableImplementationTask([entry(terminal)])).toBeNull();
    },
  );

  it("prefers a task with a PR over a merely-running one", () => {
    const running = makeTask("running", { status: "in_progress" });
    const withPr = makeTask("withPr", {
      status: "completed",
      prUrl: "https://gh/pr/9",
    });
    // Order shouldn't matter — the PR task wins either way.
    expect(
      findContinuableImplementationTask([entry(running), entry(withPr)]),
    ).toBe(withPr);
    expect(
      findContinuableImplementationTask([entry(withPr), entry(running)]),
    ).toBe(withPr);
  });

  it("ignores a failed run that produced no PR even when one is running", () => {
    const failed = makeTask("failed", { status: "failed" });
    const running = makeTask("running", { status: "queued" });
    expect(
      findContinuableImplementationTask([entry(failed), entry(running)]),
    ).toBe(running);
  });
});

describe("getTaskPrUrl", () => {
  it("returns the PR url when present", () => {
    expect(
      getTaskPrUrl(makeTask("t", { status: "completed", prUrl: "https://x" })),
    ).toBe("https://x");
  });

  it("returns null when there is no run or no PR", () => {
    expect(getTaskPrUrl(makeTask("t"))).toBeNull();
    expect(getTaskPrUrl(makeTask("t", { status: "in_progress" }))).toBeNull();
  });
});
