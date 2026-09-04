import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";

import {
  canReleaseReport,
  describeReportOwner,
  reportWorkState,
} from "./reportOwnership";

function report(overrides: Partial<SignalReport>): SignalReport {
  return {
    id: "r",
    title: "A report",
    summary: null,
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    artefact_count: 0,
    ...overrides,
  } as SignalReport;
}

describe("report ownership", () => {
  describe("describeReportOwner", () => {
    it("returns null when nobody claimed the report", () => {
      expect(describeReportOwner(report({}))).toBeNull();
    });

    it("names the external agent that holds the claim", () => {
      const owner = describeReportOwner(
        report({ assignee: { kind: "agent", agent: "scout-runner" } }),
      );
      expect(owner).toMatchObject({ kind: "agent", name: "scout-runner" });
    });

    it("falls back to a generic name for an agent claim without a name", () => {
      const owner = describeReportOwner(
        report({ assignee: { kind: "agent", agent: "  " } }),
      );
      expect(owner?.name).toBe("External agent");
    });

    it.each([
      [
        { kind: "user", user: { first_name: "Ada", email: "a@example.com" } },
        "Ada",
      ],
      [{ kind: "user", user: { email: "a@example.com" } }, "a@example.com"],
      [{ kind: "task", task_id: "t-1" }, "Cloud task"],
      [{ kind: "system" }, "PostHog"],
    ])("names a %o claim", (assignee, expected) => {
      const owner = describeReportOwner(
        report({ assignee } as Partial<SignalReport>),
      );
      expect(owner?.name).toBe(expected);
    });
  });

  describe("reportWorkState", () => {
    it("uses the server value when present", () => {
      expect(reportWorkState(report({ work_state: "working" }))).toBe(
        "working",
      );
    });

    it.each([
      // A legacy report carries no work_state, only the PR fields.
      [{ status: "resolved" }, "done"],
      [{ implementation_pr_url: "https://github.com/o/r/pull/1" }, "in_review"],
      [
        {
          implementation_pr_url: "https://github.com/o/r/pull/1",
          implementation_pr_merged: true,
        },
        "unclaimed",
      ],
      [{}, "unclaimed"],
    ])("derives %o for a report without work_state", (overrides, expected) => {
      expect(reportWorkState(report(overrides as Partial<SignalReport>))).toBe(
        expected,
      );
    });
  });

  describe("canReleaseReport", () => {
    it.each([
      [{}, false],
      [{ assignee: { kind: "agent", agent: "scout-runner" } }, true],
      [
        {
          assignee: { kind: "agent", agent: "scout-runner" },
          status: "resolved",
        },
        false,
      ],
    ])("returns %o -> %s", (overrides, expected) => {
      expect(canReleaseReport(report(overrides as Partial<SignalReport>))).toBe(
        expected,
      );
    });
  });
});
