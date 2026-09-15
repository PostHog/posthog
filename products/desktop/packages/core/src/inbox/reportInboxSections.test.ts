import type { SignalReport, Task, TaskRunStatus } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";

import {
  deriveReportImplementationState,
  needsImplementationDecision,
} from "./reportImplementation";
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
