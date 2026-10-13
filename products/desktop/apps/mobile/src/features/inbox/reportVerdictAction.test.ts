import type {
  SignalReport,
  SignalReportActionability,
  SignalReportStatus,
} from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  type ReportVerdictAction,
  resolveReportVerdictAction,
} from "./reportVerdictAction";

function report(overrides: Partial<SignalReport>): SignalReport {
  return {
    id: "r1",
    title: "A report",
    summary: "",
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    artefact_count: 0,
    ...overrides,
  };
}

describe("resolveReportVerdictAction", () => {
  const cases: Array<{
    name: string;
    overrides: Partial<SignalReport>;
    expected: ReportVerdictAction;
  }> = [
    {
      name: "ready + immediately actionable → start",
      overrides: { status: "ready", actionability: "immediately_actionable" },
      expected: { kind: "start", label: "Start task", awaitingInput: false },
    },
    {
      name: "ready + requires human input → implement as new task",
      overrides: { status: "ready", actionability: "requires_human_input" },
      expected: {
        kind: "start",
        label: "Implement as new task",
        awaitingInput: true,
      },
    },
    {
      name: "pending_input → implement as new task",
      overrides: { status: "pending_input" },
      expected: {
        kind: "start",
        label: "Implement as new task",
        awaitingInput: true,
      },
    },
    {
      name: "live PR takes precedence over start",
      overrides: {
        status: "ready",
        actionability: "immediately_actionable",
        implementation_pr_url: "https://github.com/o/r/pull/1",
      },
      expected: { kind: "view_pr", url: "https://github.com/o/r/pull/1" },
    },
    {
      name: "merged PR is not live: offer a fresh start",
      overrides: {
        status: "ready",
        actionability: "immediately_actionable",
        implementation_pr_url: "https://github.com/o/r/pull/1",
        implementation_pr_merged: true,
      },
      expected: { kind: "start", label: "Start task", awaitingInput: false },
    },
    {
      name: "non-GitHub PR url is not trusted: no action, not presented as a PR",
      overrides: {
        status: "ready",
        actionability: "immediately_actionable",
        implementation_pr_url: "https://attacker.example/pull/1",
      },
      expected: null,
    },
    {
      name: "already addressed → no action",
      overrides: {
        status: "ready",
        actionability: "immediately_actionable",
        already_addressed: true,
      },
      expected: null,
    },
    {
      name: "not actionable → no action",
      overrides: { status: "ready", actionability: "not_actionable" },
      expected: null,
    },
    {
      name: "in progress → no action",
      overrides: { status: "in_progress" },
      expected: null,
    },
    {
      name: "failed → no action",
      overrides: { status: "failed" },
      expected: null,
    },
  ];

  it.each(cases)("$name", ({ overrides, expected }) => {
    expect(resolveReportVerdictAction(report(overrides))).toEqual(expected);
  });

  it.each<SignalReportStatus>(["resolved", "suppressed", "deleted"])(
    "terminal status %s offers no action even with a live PR",
    (status) => {
      expect(
        resolveReportVerdictAction(
          report({
            status,
            actionability:
              "immediately_actionable" as SignalReportActionability,
            implementation_pr_url: "https://github.com/o/r/pull/1",
          }),
        ),
      ).toBeNull();
    },
  );
});
