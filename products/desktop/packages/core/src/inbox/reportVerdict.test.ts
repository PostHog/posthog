import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";

import { deriveReportVerdict } from "./reportVerdict";

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

describe("deriveReportVerdict", () => {
  it.each([
    // Non-ready lifecycle states speak for themselves, whatever the artefacts say.
    [{ status: "resolved" }, false, "Resolved", "info"],
    [{ status: "suppressed" }, false, "Archived", "info"],
    [{ status: "deleted" }, false, "Archived", "info"],
    [{ status: "failed" }, false, "Run failed", "danger"],
    [{ status: "pending_input" }, false, "Waiting on you", "decision"],
    [{ status: "potential" }, false, "Waiting for new signals", "info"],
    [
      { status: "potential", dismissal_reason: "already_fixed" },
      false,
      "Dismissed until new signals",
      "info",
    ],
    [
      { status: "potential", dismissal_reason: "already_fixed" },
      true,
      "Dismissed until new signals",
      "info",
    ],
    [{ status: "candidate" }, false, "Waiting to investigate", "info"],
    [
      { status: "in_progress", dismissal_reason: "already_fixed" },
      false,
      "Agent investigating",
      "progress",
    ],
    [{ status: "in_progress" }, false, "Agent investigating", "progress"],
    // Ready: an existing PR outranks actionability, which outranks nothing.
    [
      { status: "ready", actionability: "immediately_actionable" },
      true,
      "Review the open PR",
      "decision",
    ],
    [
      { status: "ready", already_addressed: true },
      false,
      "Likely already fixed",
      "info",
    ],
    [
      { status: "ready", actionability: "immediately_actionable" },
      false,
      "Needs your decision",
      "decision",
    ],
    [
      { status: "ready", actionability: "requires_human_input" },
      false,
      "Needs your direction",
      "decision",
    ],
    [
      { status: "ready", actionability: "not_actionable" },
      false,
      "Not actionable after research",
      "info",
    ],
    [{ status: "ready" }, false, "Ready for review", "decision"],
  ] as const)(
    "%j with hasExistingPr=%s reads %j",
    (overrides, hasExistingPr, title, tone) => {
      const verdict = deriveReportVerdict(
        report(overrides as Partial<SignalReport>),
        { hasExistingPr },
      );
      expect(verdict.title).toBe(title);
      expect(verdict.tone).toBe(tone);
    },
  );

  it("a PR on a non-ready report does not override the lifecycle state", () => {
    const verdict = deriveReportVerdict(report({ status: "in_progress" }), {
      hasExistingPr: true,
    });
    expect(verdict.title).toBe("Agent investigating");
  });

  it("carries the research reasoning on a report parked as not actionable", () => {
    const verdict = deriveReportVerdict(
      report({ status: "ready", actionability: "not_actionable" }),
      {
        hasExistingPr: false,
        actionabilityExplanation: "  The rate limit is working as designed.  ",
      },
    );
    expect(verdict.rationale).toBe("The rate limit is working as designed.");
    expect(verdict.body).toContain("Read the reasoning");
  });

  it.each([undefined, null, "   "])(
    "omits the rationale when research recorded %j",
    (explanation) => {
      const verdict = deriveReportVerdict(
        report({ status: "ready", actionability: "not_actionable" }),
        { hasExistingPr: false, actionabilityExplanation: explanation },
      );
      expect(verdict.rationale).toBeUndefined();
      expect(verdict.body).toContain("Open Activity for the judgment");
    },
  );

  it("keeps the research verdict over a running task that has no PR", () => {
    const verdict = deriveReportVerdict(
      report({ status: "ready", actionability: "not_actionable" }),
      { hasExistingPr: false, hasLiveImplementationTask: true },
    );
    expect(verdict.title).toBe("Not actionable after research");
  });

  it("still leads with a real PR on a report research parked", () => {
    const verdict = deriveReportVerdict(
      report({ status: "ready", actionability: "not_actionable" }),
      { hasExistingPr: true, hasLiveImplementationTask: true },
    );
    expect(verdict.title).toBe("Review the open PR");
  });

  it("names the task, not a PR, while an actionable report is being fixed", () => {
    const verdict = deriveReportVerdict(
      report({ status: "ready", actionability: "immediately_actionable" }),
      { hasExistingPr: false, hasLiveImplementationTask: true },
    );
    expect(verdict.title).toBe("Implementation in progress");
  });
});
