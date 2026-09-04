import { ApiRequestError } from "@posthog/api-client/fetcher";
import type { Task, TaskRun, TaskRunStatus } from "@posthog/shared/types";
import { describe, expect, it, vi } from "vitest";
import {
  derivePurpose,
  fetchReportTasks,
  findContinuableImplementationTask,
  findLatestDiscussionTask,
  findPendingStartedTaskId,
  getTaskPrUrl,
  type ReportTaskData,
  type ReportTaskPurpose,
} from "./useReportTasks";

function makeTask(
  id: string,
  run?: {
    status?: TaskRunStatus;
    prUrl?: string | null;
    prMerged?: boolean;
    prState?: string;
  },
): Task {
  let output: Record<string, unknown> | null = null;
  if (run?.prUrl) {
    output = { pr_url: run.prUrl };
    if (run.prMerged) output.pr_merged = true;
    if (run.prState) output.pr_state = run.prState;
  }
  const latest_run: TaskRun | undefined = run
    ? {
        id: `${id}-run`,
        task: id,
        team: 1,
        branch: null,
        status: run.status ?? "in_progress",
        log_url: "",
        error_message: null,
        output,
        state: {},
        created_at: "2026-06-24T10:00:00Z",
        updated_at: "2026-06-24T10:00:00Z",
        completed_at: null,
      }
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
  };
}

function entry(
  task: Task,
  purpose: ReportTaskPurpose = "implementation",
): ReportTaskData {
  return { task, purpose, purposeLabel: purpose, startedAt: task.created_at };
}

describe("fetchReportTasks", () => {
  function artefact(taskId: string, type: string) {
    return {
      id: `artefact-${taskId}`,
      type: "task_run",
      content: { task_id: taskId, product: "signals", type },
      created_at: "2026-06-24T10:00:00Z",
    };
  }

  const getArtefacts = vi.fn();

  function client(
    artefacts: ReturnType<typeof artefact>[],
    getTask: (taskId: string) => Promise<Task>,
  ) {
    getArtefacts.mockResolvedValue({
      results: artefacts,
      count: artefacts.length,
    });
    return {
      getSignalReportArtefacts: getArtefacts,
      getTask: (taskId: string) => getTask(taskId),
    } as unknown as Parameters<typeof fetchReportTasks>[0];
  }

  it("keeps the surviving runs when a task_run artefact points at a deleted task", async () => {
    const implementation = makeTask("impl", { prUrl: "https://gh/pr/1" });
    const tasks = await fetchReportTasks(
      client(
        [artefact("scout", "scout"), artefact("impl", "implementation")],
        async (taskId) => {
          if (taskId === "scout") {
            throw new ApiRequestError(404, '{"detail":"Not found."}');
          }
          return implementation;
        },
      ),
      "report-1",
    );

    expect(tasks.map((t) => t.task)).toEqual([implementation]);
    // Runs come from the whole log, so the oldest task_run is not truncated away.
    expect(getArtefacts).toHaveBeenCalledWith("report-1", { limit: 1000 });
  });

  it("fails the fetch when a task lookup errors for any other reason", async () => {
    await expect(
      fetchReportTasks(
        client([artefact("impl", "implementation")], async () => {
          throw new ApiRequestError(500, '{"detail":"Server error."}');
        }),
        "report-1",
      ),
    ).rejects.toThrow(ApiRequestError);
  });
});

describe("derivePurpose", () => {
  it.each([
    ["research", "Research"],
    ["implementation", "Implementation"],
    ["discussion", "Discussion"],
    ["scout", "Scout"],
    ["a_future_run_type", "A future run type"],
  ])("keeps the signals %s run in the list", (type, purposeLabel) => {
    expect(derivePurpose({ product: "signals", type })?.purposeLabel).toBe(
      purposeLabel,
    );
  });

  it("drops repo selection plumbing", () => {
    expect(
      derivePurpose({ product: "signals", type: "repo_selection" }),
    ).toBeNull();
  });

  it("labels a custom agent run with its product and type", () => {
    expect(derivePurpose({ product: "my_agent", type: "sweep" })).toEqual({
      purpose: "other",
      purposeLabel: "My agent — Sweep",
    });
  });
});

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

  it("treats a merged PR as history, not continuable work", () => {
    const merged = makeTask("merged", {
      status: "completed",
      prUrl: "https://gh/pr/9",
      prMerged: true,
    });
    expect(findContinuableImplementationTask([entry(merged)])).toBeNull();
  });

  it("continues a still-open PR and skips a merged one", () => {
    const merged = makeTask("merged", {
      status: "completed",
      prUrl: "https://gh/pr/1",
      prMerged: true,
    });
    const open = makeTask("open", {
      status: "completed",
      prUrl: "https://gh/pr/2",
    });
    expect(
      findContinuableImplementationTask([entry(merged), entry(open)]),
    ).toBe(open);
  });
});

describe("findPendingStartedTaskId", () => {
  it("bridges a started task until it appears in the report tasks", () => {
    expect(findPendingStartedTaskId(undefined, "started")).toBe("started");
    expect(findPendingStartedTaskId([], "started")).toBe("started");
    expect(
      findPendingStartedTaskId([entry(makeTask("started"))], "started"),
    ).toBeNull();
  });

  it("returns null when there is no started task", () => {
    expect(findPendingStartedTaskId([], null)).toBeNull();
  });
});

describe("findLatestDiscussionTask", () => {
  it("returns the newest discussion and ignores other purposes", () => {
    const older = entry(makeTask("old-chat"), "discussion");
    older.startedAt = "2026-06-20T10:00:00Z";
    const newer = entry(makeTask("new-chat"), "discussion");
    newer.startedAt = "2026-06-24T10:00:00Z";
    const impl = entry(makeTask("impl", { prUrl: "https://gh/pr/1" }));
    expect(findLatestDiscussionTask([impl, older, newer])).toBe(newer.task);
    expect(findLatestDiscussionTask([impl])).toBeNull();
    expect(findLatestDiscussionTask(undefined)).toBeNull();
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
