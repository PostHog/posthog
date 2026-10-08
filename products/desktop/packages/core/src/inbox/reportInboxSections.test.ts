import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { SignalReport, Task, TaskRunStatus } from "@posthog/shared/types";
import { describe, expect, it, vi } from "vitest";
import {
  deriveReportImplementationState,
  needsImplementationDecision,
} from "./reportImplementation";
import { ReportImplementationService } from "./reportImplementationService";
import { partitionInboxReports } from "./reportInboxSections";

function report(overrides: Partial<SignalReport>): SignalReport {
  return {
    id: overrides.id ?? "r",
    title: "A report",
    summary: null,
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    artefact_count: 0,
    actionability: "immediately_actionable",
    ...overrides,
  } as SignalReport;
}

function implementationTask(
  status: TaskRunStatus,
  output: Record<string, unknown> | null = null,
): Task {
  return {
    id: "implementation-1",
    task_number: 1,
    slug: "implementation-1",
    title: "Fix the example report",
    description: "Create a PR for the report.",
    origin_product: "signal_report",
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
    latest_run: {
      id: "run-1",
      task: "implementation-1",
      team: 1,
      branch: null,
      status,
      log_url: "",
      error_message: null,
      output,
      state: {},
      created_at: "2026-09-01T00:00:00Z",
      updated_at: "2026-09-01T00:00:00Z",
      completed_at: null,
    },
  };
}

describe("reportInboxSections", () => {
  it("batches and deduplicates task lookups for a full report page", async () => {
    const reports = Array.from({ length: 400 }, (_, index) =>
      report({
        id: `report-${index}`,
        assignee: { kind: "task", task_id: `task-${index % 200}` },
      }),
    );
    const summaries = Array.from({ length: 200 }, (_, index) => ({
      id: `task-${index}`,
      latest_run: { status: "in_progress" },
    }));
    const client = {
      getTaskSummaries: vi.fn().mockResolvedValue(summaries),
      getTask: vi.fn(),
    };
    const service = new ReportImplementationService();
    const states = await service.loadStates(
      client as unknown as PostHogAPIClient,
      reports,
    );
    expect(client.getTaskSummaries).toHaveBeenCalledExactlyOnceWith(
      summaries.map((summary) => summary.id),
    );
    expect(client.getTask).not.toHaveBeenCalled();
    expect(states.size).toBe(400);
    expect([...states.values()].every((state) => state === "working")).toBe(
      true,
    );
  });

  it("keeps missing tasks visible and pending input actionable", async () => {
    const client = { getTaskSummaries: vi.fn().mockResolvedValue([]) };
    const states = await new ReportImplementationService().loadStates(
      client as unknown as PostHogAPIClient,
      [
        report({
          id: "missing",
          assignee: { kind: "task", task_id: "missing" },
        }),
        report({
          id: "input",
          status: "pending_input",
          assignee: { kind: "task", task_id: "input" },
        }),
      ],
    );
    expect(states.get("missing")).toBe("unknown");
    expect(states.get("input")).toBe("needs_input");
  });

  it.each([
    [null, null, "no_pr"],
    ["https://github.com/example/project/pull/1", "open", "in_review"],
    ["https://github.com/example/project/pull/1", "draft", "in_review"],
    ["https://github.com/example/project/pull/1", "unknown", "in_review"],
    ["https://github.com/example/project/pull/1", "merged", "no_pr"],
    ["https://github.com/example/project/pull/1", "closed", "no_pr"],
  ])(
    "loads completed tasks with PR state %s / %s without detail requests",
    async (prUrl, prState, expected) => {
      const summaries = Array.from({ length: 25 }, (_, index) => ({
        id: `task-${index}`,
        latest_run: {
          id: `run-${index}`,
          status: "completed",
          pr_url: prUrl,
          pr_state: prState,
        },
      }));
      const reports = summaries.map((summary) =>
        report({
          id: summary.id,
          assignee: { kind: "task", task_id: summary.id },
        }),
      );
      const client = {
        getTaskSummaries: vi.fn().mockResolvedValue(summaries),
        getTask: vi.fn(),
      };
      const states = await new ReportImplementationService().loadStates(
        client as unknown as PostHogAPIClient,
        reports,
      );
      expect(client.getTaskSummaries).toHaveBeenCalledExactlyOnceWith(
        summaries.map((summary) => summary.id),
      );
      expect(client.getTask).not.toHaveBeenCalled();
      expect([...states.values()]).toEqual(reports.map(() => expected));
    },
  );

  it("uses fresh summaries instead of cached details after a server upgrade", async () => {
    const task = implementationTask("completed");
    const summary = {
      ...task,
      latest_run: { id: "run-1", status: "completed" },
    };
    const client = {
      getTaskSummaries: vi.fn().mockResolvedValue([summary]),
      getTask: vi.fn().mockResolvedValue(task),
    };
    const reports = [report({ assignee: { kind: "task", task_id: task.id } })];
    const service = new ReportImplementationService();
    const load = () =>
      service.loadStates(client as unknown as PostHogAPIClient, reports);
    expect((await load()).get("r")).toBe("no_pr");
    for (const [prState, expected] of [
      ["open", "in_review"],
      ["merged", "no_pr"],
      ["open", "in_review"],
      ["closed", "no_pr"],
    ]) {
      client.getTaskSummaries.mockResolvedValue([
        {
          ...summary,
          latest_run: {
            ...summary.latest_run,
            pr_url: "https://github.com/example/project/pull/1",
            pr_state: prState,
          },
        },
      ]);
      expect((await load()).get("r")).toBe(expected);
    }
    expect(client.getTaskSummaries).toHaveBeenCalledTimes(5);
    expect(client.getTask).toHaveBeenCalledOnce();
  });

  it.each([{}, { pr_url: null }, { pr_state: null }])(
    "loads details only for summaries with missing PR fields: %j",
    async (fields) => {
      const task = implementationTask("completed", {
        pr_url: "https://github.com/example/project/pull/1",
      });
      const client = {
        getTaskSummaries: vi.fn().mockResolvedValue([
          {
            id: task.id,
            latest_run: { id: "run-1", status: "completed", ...fields },
          },
          {
            id: "no-pr",
            latest_run: {
              id: "run-2",
              status: "completed",
              pr_url: null,
              pr_state: null,
            },
          },
        ]),
        getTask: vi.fn().mockResolvedValue(task),
      };
      const states = await new ReportImplementationService().loadStates(
        client as unknown as PostHogAPIClient,
        [task.id, "no-pr"].map((id) =>
          report({ id, assignee: { kind: "task", task_id: id } }),
        ),
      );
      expect(states.get(task.id)).toBe("in_review");
      expect(states.get("no-pr")).toBe("no_pr");
      expect(client.getTask).toHaveBeenCalledExactlyOnceWith(task.id);
    },
  );

  it("checks legacy completed PR output once per task version and client", async () => {
    const task = implementationTask("completed", {
      pr_url: "https://github.com/example/project/pull/1",
    });
    const summary = {
      ...task,
      latest_run: { id: "run-1", status: "completed" },
    };
    const client = {
      getTaskSummaries: vi.fn().mockResolvedValue([summary]),
      getTask: vi.fn().mockResolvedValue(task),
    };
    const reports = [report({ assignee: { kind: "task", task_id: task.id } })];
    const service = new ReportImplementationService();
    const load = () =>
      service.loadStates(client as unknown as PostHogAPIClient, reports);
    expect((await load()).get("r")).toBe("in_review");
    await load();
    expect(client.getTask).toHaveBeenCalledOnce();
    client.getTaskSummaries.mockResolvedValue([
      { ...summary, updated_at: "2026-09-02T00:00:00Z" },
    ]);
    client.getTask.mockResolvedValue(
      implementationTask("completed", { pr_state: "closed" }),
    );
    expect((await load()).get("r")).toBe("no_pr");
    expect(client.getTask).toHaveBeenCalledTimes(2);
    const otherClient = {
      ...client,
      getTask: vi.fn().mockResolvedValue(implementationTask("completed")),
    };
    await service.loadStates(
      otherClient as unknown as PostHogAPIClient,
      reports,
    );
    expect(otherClient.getTask).toHaveBeenCalledOnce();
  });

  it("refreshes completed PR output even if the task timestamp does not change", async () => {
    const now = vi.spyOn(Date, "now").mockReturnValue(0);
    try {
      const task = implementationTask("completed", {
        pr_url: "https://github.com/example/project/pull/1",
      });
      const client = {
        getTaskSummaries: vi
          .fn()
          .mockResolvedValue([
            { ...task, latest_run: { id: "run-1", status: "completed" } },
          ]),
        getTask: vi
          .fn()
          .mockResolvedValueOnce(task)
          .mockResolvedValue(
            implementationTask("completed", { pr_state: "closed" }),
          ),
      };
      const service = new ReportImplementationService();
      const reports = [
        report({ assignee: { kind: "task", task_id: task.id } }),
      ];
      expect(
        (
          await service.loadStates(
            client as unknown as PostHogAPIClient,
            reports,
          )
        ).get("r"),
      ).toBe("in_review");
      now.mockReturnValue(5 * 60_000);
      expect(
        (
          await service.loadStates(
            client as unknown as PostHogAPIClient,
            reports,
          )
        ).get("r"),
      ).toBe("no_pr");
    } finally {
      now.mockRestore();
    }
  });

  it("limits completed-task detail requests to ten at a time", async () => {
    const task = implementationTask("completed");
    const summaries = Array.from({ length: 25 }, (_, index) => ({
      ...task,
      id: `task-${index}`,
    }));
    const reports = summaries.map((summary) =>
      report({
        id: summary.id,
        assignee: { kind: "task", task_id: summary.id },
      }),
    );
    let active = 0;
    let maximum = 0;
    const client = {
      getTaskSummaries: vi.fn().mockResolvedValue(summaries),
      getTask: vi.fn().mockImplementation(async () => {
        active++;
        maximum = Math.max(maximum, active);
        await Promise.resolve();
        active--;
        return task;
      }),
    };
    const states = await new ReportImplementationService().loadStates(
      client as unknown as PostHogAPIClient,
      reports,
    );
    expect(client.getTask).toHaveBeenCalledTimes(25);
    expect(maximum).toBe(10);
    expect([...states.values()].every((state) => state === "no_pr")).toBe(true);
  });

  it("recovers a failed completed-task lookup on the next refresh", async () => {
    const task = implementationTask("completed");
    const client = {
      getTaskSummaries: vi
        .fn()
        .mockResolvedValue([
          { ...task, latest_run: { id: "run-1", status: "completed" } },
        ]),
      getTask: vi
        .fn()
        .mockRejectedValueOnce(new Error("Unavailable"))
        .mockResolvedValue(task),
    };
    const service = new ReportImplementationService();
    const reports = [report({ assignee: { kind: "task", task_id: task.id } })];
    expect(
      (
        await service.loadStates(client as unknown as PostHogAPIClient, reports)
      ).get("r"),
    ).toBe("unknown");
    expect(
      (
        await service.loadStates(client as unknown as PostHogAPIClient, reports)
      ).get("r"),
    ).toBe("no_pr");
  });

  it.each([
    [{ status: "ready" }, "needsPr"],
    [
      {
        status: "ready",
        implementation_pr_url: "https://github.com/o/r/pull/1",
      },
      "reviewAndMerge",
    ],
    [{ status: "pending_input" }, "needsPr"],
    [{ status: "ready", actionability: "not_actionable" }, null],
    [
      {
        status: "pending_input",
        implementation_pr_url: "https://github.com/o/r/pull/2",
      },
      null,
    ],
    [{ status: "failed" }, null],
    [{ status: "in_progress" }, null],
    [{ status: "candidate" }, null],
  ] as const)("%j lands in %s", (overrides, section) => {
    const sections = partitionInboxReports([
      report(overrides as Partial<SignalReport>),
    ]);
    expect(sections.reviewAndMerge.length).toBe(
      section === "reviewAndMerge" ? 1 : 0,
    );
    expect(sections.needsPr.length).toBe(section === "needsPr" ? 1 : 0);
  });

  it("partition preserves the list's own order within each section", () => {
    const sections = partitionInboxReports([
      report({ id: "n1" }),
      report({ id: "r1", implementation_pr_url: "https://gh/pr/1" }),
      report({ id: "n2", status: "pending_input" }),
      report({ id: "r2", implementation_pr_url: "https://gh/pr/2" }),
    ]);
    expect(sections.reviewAndMerge.map((r) => r.id)).toEqual(["r1", "r2"]);
    expect(sections.needsPr.map((r) => r.id)).toEqual(["n1", "n2"]);
  });
  it.each([
    ["queued", "working", false],
    ["not_started", "working", false],
    ["in_progress", "working", false],
    ["failed", "failed", true],
    ["cancelled", "cancelled", true],
    ["completed", "no_pr", true],
  ] as const)(
    "keeps a %s implementation in the correct queue",
    (status, expected, needsDecision) => {
      const assignedReport = report({
        assignee: { kind: "task", task_id: "implementation-1" },
        work_state: "working",
      });
      const task = implementationTask(status);
      const state = deriveReportImplementationState(assignedReport, task);
      expect(state).toBe(expected);
      expect(needsImplementationDecision(state)).toBe(needsDecision);
      expect(assignedReport.status).toBe("ready");
      expect(partitionInboxReports([assignedReport]).needsPr).toEqual([
        assignedReport,
      ]);
    },
  );

  it.each([
    ["ready", undefined, false, "checking", false],
    ["ready", undefined, true, "unknown", true],
    ["pending_input", undefined, false, "needs_input", true],
    ["resolved", undefined, false, null, true],
    ["suppressed", undefined, false, null, true],
  ] as const)(
    "handles %s reports with unavailable task state",
    (status, task, failed, expected, needsDecision) => {
      const state = deriveReportImplementationState(
        report({
          status,
          assignee: { kind: "task", task_id: "implementation-1" },
        }),
        task,
        failed,
      );
      expect(state).toBe(expected);
      expect(needsImplementationDecision(state)).toBe(needsDecision);
    },
  );

  it("keeps a finished PR out of triage before report metadata refreshes", () => {
    const state = deriveReportImplementationState(
      report({ assignee: { kind: "task", task_id: "implementation-1" } }),
      implementationTask("completed", {
        pr_url: "https://github.com/example/project/pull/1",
      }),
    );
    expect(state).toBe("in_review");
    expect(needsImplementationDecision(state)).toBe(false);
  });

  it("does not hide reports on servers without task assignments", () => {
    expect(
      needsImplementationDecision(
        deriveReportImplementationState(report({}), undefined),
      ),
    ).toBe(true);
  });
  it.each(["merged", "closed"])(
    "returns reports with a %s earlier fix to triage",
    (prState) => {
      const state = deriveReportImplementationState(
        report({ assignee: { kind: "task", task_id: "implementation-1" } }),
        implementationTask("completed", {
          pr_url: "https://github.com/example/project/pull/1",
          pr_state: prState,
        }),
      );
      expect(state).toBe("no_pr");
      expect(needsImplementationDecision(state)).toBe(true);
    },
  );
});
