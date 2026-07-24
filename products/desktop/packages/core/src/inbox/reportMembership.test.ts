import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  computeInboxTabCounts,
  countInboxScopeReports,
  EMPTY_TAB_COUNTS,
  INBOX_SCOPE_ENTIRE_PROJECT,
  INBOX_SCOPE_FOR_YOU,
  isAgentRunReport,
  isDismissedReport,
  isExcludedFromInbox,
  isInboxDetailPath,
  isPullRequestReport,
  isReportTabReport,
  matchesReviewerScope,
  partitionRunsTabReports,
  teammateInboxScope,
} from "./reportMembership";

function fakeReport(overrides: Partial<SignalReport> = {}): SignalReport {
  return {
    id: "r1",
    title: "Test report",
    summary: "Summary",
    status: "ready",
    total_weight: 1,
    signal_count: 1,
    created_at: "2026-06-05T00:00:00Z",
    updated_at: "2026-06-05T00:00:00Z",
    artefact_count: 0,
    priority: null,
    actionability: null,
    is_suggested_reviewer: false,
    source_products: [],
    implementation_pr_url: null,
    ...overrides,
  };
}

describe("isDismissedReport", () => {
  it.each(["suppressed", "resolved"] as const)(
    "matches %s reports",
    (status) => {
      expect(isDismissedReport(fakeReport({ status }))).toBe(true);
    },
  );

  it.each([
    "potential",
    "candidate",
    "in_progress",
    "pending_input",
    "ready",
    "failed",
    "deleted",
  ] as const)("does not match %s reports", (status) => {
    expect(isDismissedReport(fakeReport({ status }))).toBe(false);
  });
});

describe("isInboxDetailPath", () => {
  it("matches detail paths for each inbox tab", () => {
    expect(isInboxDetailPath("/code/inbox/pulls/abc")).toBe(true);
    expect(isInboxDetailPath("/code/inbox/reports/abc")).toBe(true);
    expect(isInboxDetailPath("/code/inbox/runs/abc")).toBe(true);
  });

  it("does not match tab list paths", () => {
    expect(isInboxDetailPath("/code/inbox/pulls")).toBe(false);
    expect(isInboxDetailPath("/code/inbox/reports")).toBe(false);
    expect(isInboxDetailPath("/code/inbox/runs")).toBe(false);
    expect(isInboxDetailPath("/code/inbox")).toBe(false);
  });

  it("does not match paths with extra trailing segments", () => {
    expect(isInboxDetailPath("/code/inbox/pulls/abc/edit")).toBe(false);
    expect(isInboxDetailPath("/code/inbox/runs/abc/")).toBe(false);
  });

  it("does not match unrelated paths", () => {
    expect(isInboxDetailPath("/code/agents")).toBe(false);
    expect(isInboxDetailPath("/code/inbox/agents")).toBe(false);
    expect(isInboxDetailPath("/")).toBe(false);
  });
});

describe("inbox scope", () => {
  it("counts for-you and entire-project scopes", () => {
    const reports = [
      fakeReport({ id: "1", is_suggested_reviewer: true }),
      fakeReport({ id: "2", is_suggested_reviewer: false }),
      fakeReport({
        id: "3",
        status: "suppressed",
        is_suggested_reviewer: true,
      }),
    ];

    expect(countInboxScopeReports(reports, INBOX_SCOPE_FOR_YOU)).toBe(1);
    expect(countInboxScopeReports(reports, INBOX_SCOPE_ENTIRE_PROJECT)).toBe(2);
  });

  it("builds teammate scope keys", () => {
    expect(teammateInboxScope("uuid-1")).toBe("teammate:uuid-1");
  });
});

describe("tabFilters", () => {
  describe("isPullRequestReport", () => {
    it("returns true when a ready report has an implementation PR", () => {
      expect(
        isPullRequestReport(
          fakeReport({
            status: "ready",
            implementation_pr_url: "https://gh/p/1",
          }),
        ),
      ).toBe(true);
    });

    it("returns false when implementation_pr_url is null", () => {
      expect(
        isPullRequestReport(
          fakeReport({ status: "ready", implementation_pr_url: null }),
        ),
      ).toBe(false);
    });

    it("returns false for a PR whose report is no longer ready", () => {
      expect(
        isPullRequestReport(
          fakeReport({
            status: "candidate",
            implementation_pr_url: "https://gh/p/1",
          }),
        ),
      ).toBe(false);
    });

    it("returns false for a still-running PR", () => {
      expect(
        isPullRequestReport(
          fakeReport({
            status: "in_progress",
            implementation_pr_url: "https://gh/p/1",
          }),
        ),
      ).toBe(false);
    });

    it("returns false when report is suppressed", () => {
      expect(
        isPullRequestReport(
          fakeReport({
            implementation_pr_url: "https://gh/p/1",
            status: "suppressed",
          }),
        ),
      ).toBe(false);
    });
  });

  describe("isExcludedFromInbox", () => {
    it("returns true for suppressed, resolved and deleted", () => {
      expect(isExcludedFromInbox(fakeReport({ status: "suppressed" }))).toBe(
        true,
      );
      expect(isExcludedFromInbox(fakeReport({ status: "resolved" }))).toBe(
        true,
      );
      expect(isExcludedFromInbox(fakeReport({ status: "deleted" }))).toBe(true);
    });

    it("returns false for failed (surfaced inside the Runs tab) and other pipeline statuses", () => {
      expect(isExcludedFromInbox(fakeReport({ status: "failed" }))).toBe(false);
      expect(isExcludedFromInbox(fakeReport({ status: "ready" }))).toBe(false);
    });
  });

  describe("isAgentRunReport", () => {
    it("returns true when status is in_progress", () => {
      expect(isAgentRunReport(fakeReport({ status: "in_progress" }))).toBe(
        true,
      );
    });

    it("returns true when status is pending_input", () => {
      expect(isAgentRunReport(fakeReport({ status: "pending_input" }))).toBe(
        true,
      );
    });

    it("returns false for ready", () => {
      expect(isAgentRunReport(fakeReport({ status: "ready" }))).toBe(false);
    });
  });

  describe("isReportTabReport", () => {
    it("excludes reports with a PR", () => {
      expect(
        isReportTabReport(
          fakeReport({ implementation_pr_url: "https://gh/p/1" }),
        ),
      ).toBe(false);
    });

    it("excludes any PR-bearing report rather than surfacing it as a Report", () => {
      expect(
        isReportTabReport(
          fakeReport({
            status: "candidate",
            implementation_pr_url: "https://gh/p/1",
          }),
        ),
      ).toBe(false);
    });

    it("excludes in-progress reports", () => {
      expect(isReportTabReport(fakeReport({ status: "in_progress" }))).toBe(
        false,
      );
    });

    it("includes ready non-PR reports", () => {
      expect(
        isReportTabReport(
          fakeReport({ status: "ready", implementation_pr_url: null }),
        ),
      ).toBe(true);
    });

    it("excludes pending_input reports (they go to Runs)", () => {
      expect(
        isReportTabReport(
          fakeReport({ status: "pending_input", implementation_pr_url: null }),
        ),
      ).toBe(false);
    });
  });

  describe("matchesReviewerScope", () => {
    it("'for-you' keeps reports addressed to me", () => {
      expect(
        matchesReviewerScope(
          fakeReport({ is_suggested_reviewer: true }),
          "for-you",
        ),
      ).toBe(true);
      expect(
        matchesReviewerScope(
          fakeReport({ is_suggested_reviewer: false }),
          "for-you",
        ),
      ).toBe(false);
    });

    it("'entire-project' includes every in-inbox report", () => {
      expect(
        matchesReviewerScope(
          fakeReport({ is_suggested_reviewer: false }),
          "entire-project",
        ),
      ).toBe(true);
      expect(
        matchesReviewerScope(
          fakeReport({ is_suggested_reviewer: true }),
          "entire-project",
        ),
      ).toBe(true);
    });

    it("teammate scope passes through client-filtered rows", () => {
      expect(
        matchesReviewerScope(
          fakeReport({ is_suggested_reviewer: false }),
          "teammate:abc",
        ),
      ).toBe(true);
    });
  });

  describe("computeInboxTabCounts", () => {
    const reports: SignalReport[] = [
      fakeReport({
        id: "1",
        implementation_pr_url: "https://gh/1",
        status: "ready",
        is_suggested_reviewer: true,
      }),
      fakeReport({
        id: "2",
        implementation_pr_url: "https://gh/2",
        status: "ready",
        is_suggested_reviewer: false,
      }),
      fakeReport({ id: "3", status: "ready", is_suggested_reviewer: true }),
      fakeReport({
        id: "4",
        status: "ready",
        is_suggested_reviewer: false,
      }),
      fakeReport({
        id: "5",
        status: "in_progress",
        is_suggested_reviewer: true,
      }),
      fakeReport({
        id: "6",
        status: "pending_input",
        is_suggested_reviewer: false,
      }),
    ];

    it("returns zeros for an empty list", () => {
      expect(computeInboxTabCounts([], "for-you")).toEqual(EMPTY_TAB_COUNTS);
    });

    it("for-you counts only my queue", () => {
      expect(computeInboxTabCounts(reports, "for-you")).toEqual({
        pulls: 1,
        reports: 1,
      });
    });

    it("entire-project counts the full inbox", () => {
      expect(computeInboxTabCounts(reports, "entire-project")).toEqual({
        pulls: 2,
        reports: 2,
      });
    });
  });
});

describe("partitionRunsTabReports", () => {
  it("buckets queued / live / finished and sorts each newest-first", () => {
    const queuedOld = fakeReport({
      id: "q-old",
      status: "potential",
      updated_at: "2026-06-01T00:00:00Z",
    });
    const queuedNew = fakeReport({
      id: "q-new",
      status: "candidate",
      updated_at: "2026-06-08T00:00:00Z",
    });
    const live = fakeReport({ id: "live", status: "in_progress" });
    const finishedReady = fakeReport({
      id: "fin-ready",
      status: "ready",
      updated_at: "2026-06-02T00:00:00Z",
    });
    const finishedFailed = fakeReport({
      id: "fin-failed",
      status: "failed",
      updated_at: "2026-06-09T00:00:00Z",
    });
    const pull = fakeReport({
      id: "pr",
      status: "ready",
      updated_at: "2026-06-05T00:00:00Z",
      implementation_pr_url: "https://github.com/x/y/pull/1",
    });

    const {
      queued,
      live: liveBucket,
      finished,
    } = partitionRunsTabReports([
      queuedOld,
      finishedReady,
      live,
      queuedNew,
      finishedFailed,
      pull,
    ]);

    expect(queued.map((r) => r.id)).toEqual(["q-new", "q-old"]);
    expect(liveBucket.map((r) => r.id)).toEqual(["live"]);
    // A ready PR row is also a finished run, so it lands in the finished bucket
    // and is ordered purely by recency (06-09 > 06-05 > 06-02).
    expect(finished.map((r) => r.id)).toEqual([
      "fin-failed",
      "pr",
      "fin-ready",
    ]);
  });
});
