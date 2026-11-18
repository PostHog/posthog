import type { SignalReport } from "@posthog/shared/types";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { InboxReportRowView } from "./InboxReportRowView";

function fakeReport(overrides: Partial<SignalReport> = {}): SignalReport {
  return {
    id: "r1",
    title: "Test report",
    summary: "Summary",
    status: "resolved",
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

describe("InboxReportRowView", () => {
  afterEach(cleanup);

  it("labels a resolved report Shipped only when its PR merged", () => {
    render(
      <InboxReportRowView
        report={fakeReport({ implementation_pr_merged: true })}
        onOpen={vi.fn()}
        onOpenPr={vi.fn()}
      />,
    );

    expect(screen.getByText("Shipped")).toBeTruthy();
    expect(screen.queryByText("Resolved")).toBeNull();
  });

  it("labels a resolved report Resolved, not Shipped, without a merged PR", () => {
    render(
      <InboxReportRowView
        report={fakeReport({
          implementation_pr_merged: false,
          dismissal_reason: "fixed_outside_posthog",
        })}
        onOpen={vi.fn()}
        onOpenPr={vi.fn()}
      />,
    );

    expect(screen.getByText("Resolved")).toBeTruthy();
    expect(screen.queryByText("Shipped")).toBeNull();
  });

  it("marks a draft pull request as draft", () => {
    render(
      <InboxReportRowView
        report={fakeReport({
          status: "ready",
          implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
          implementation_pr_state: "draft",
        })}
        onOpen={vi.fn()}
        onOpenPr={vi.fn()}
      />,
    );

    expect(
      screen.getByTitle("Open the draft pull request on GitHub").textContent,
    ).toContain("draft");
  });

  it("does not mark a resolved report's stale draft PR as draft", () => {
    render(
      <InboxReportRowView
        report={fakeReport({
          status: "resolved",
          implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
          implementation_pr_state: "draft",
        })}
        onOpen={vi.fn()}
        onOpenPr={vi.fn()}
      />,
    );

    expect(
      screen.queryByTitle("Open the draft pull request on GitHub"),
    ).toBeNull();
  });

  it("labels a reasonless suppressed report Archived", () => {
    render(
      <InboxReportRowView
        report={fakeReport({ status: "suppressed" })}
        onOpen={vi.fn()}
        onOpenPr={vi.fn()}
      />,
    );

    expect(screen.getByText("Archived")).toBeTruthy();
  });
});
