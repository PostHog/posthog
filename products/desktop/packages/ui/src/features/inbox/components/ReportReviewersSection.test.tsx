import type { SignalReport } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportArtefacts: () => ({ data: { count: 0, results: [] } }),
  useUpdateSuggestedReviewers: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportActionTracker", () => ({
  useReportActionTracker: () => vi.fn(),
  useReportActionResultTracker: () => vi.fn(),
}));

vi.mock("@posthog/ui/features/inbox/components/ReviewerSearchList", () => ({
  ReviewerSearchList: () => null,
}));

import { ReportReviewersSection } from "./ReportReviewersSection";

const report: SignalReport = {
  id: "report-1",
  title: "Report one",
  summary: "Summary",
  status: "ready",
  total_weight: 1,
  signal_count: 1,
  artefact_count: 0,
  created_at: "2026-08-20T09:00:00Z",
  updated_at: "2026-08-20T09:00:00Z",
};

describe("ReportReviewersSection", () => {
  it("keeps the reviewer controls available before the first assignment", () => {
    render(<ReportReviewersSection report={report} />);

    expect(screen.getByText("Suggested reviewers")).toBeInTheDocument();
    const emptyMessage = screen.getByText("No suggested reviewers yet.");
    const addButton = screen.getByRole("button", { name: "Add Reviewer" });
    expect(emptyMessage).toBeInTheDocument();
    expect(
      emptyMessage.compareDocumentPosition(addButton) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      screen.getByText("Suggested reviewers").closest("header"),
    ).not.toContainElement(addButton);
    expect(screen.queryByText("0")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "About suggested reviewers" }),
    ).toBeInTheDocument();
  });
});
