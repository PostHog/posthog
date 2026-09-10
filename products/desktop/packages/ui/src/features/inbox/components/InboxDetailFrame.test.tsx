import { FileTextIcon } from "@phosphor-icons/react";
import type { SignalReport } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/inbox/components/ReportBreadcrumbs", () => ({
  ReportBreadcrumbs: () => null,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReportDismissAction", () => ({
  useInboxReportDismissAction: () => ({
    actionButton: null,
    dialog: null,
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportSignals: () => ({ data: { report: null, signals: [] } }),
  useInboxReportArtefacts: () => ({ data: { results: [] } }),
}));

vi.mock(
  "@posthog/ui/features/inbox/components/utils/SignalReportSummaryMarkdown",
  () => ({ SignalReportSummaryMarkdown: () => null }),
);

import { InboxDetailFrame } from "./InboxDetailFrame";

const report: SignalReport = {
  id: "report-1",
  title: "feat(dashboards): add compact legend controls",
  summary: "Dashboard legends need a compact display option.",
  status: "ready",
  total_weight: 1,
  signal_count: 0,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  artefact_count: 0,
  implementation_pr_url: null,
};

describe("InboxDetailFrame", () => {
  it("keeps report context quiet and feedback after the supporting sections", () => {
    render(
      <InboxDetailFrame
        report={{ ...report, priority: "P2", is_suggested_reviewer: true }}
        fallbackTitle="Untitled report"
        summarySection={{ Icon: FileTextIcon, title: "Summary" }}
        evidenceSection={null}
        showDismiss={false}
        footer={<div>Was this report useful?</div>}
      >
        <section>Reviewers</section>
      </InboxDetailFrame>,
    );

    expect(screen.getByText("feat(dashboards)")).toBeInTheDocument();
    expect(screen.getByText("Add compact legend controls")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Summary" })).toBeInTheDocument();
    expect(screen.getAllByText("Summary")).toHaveLength(1);
    expect(screen.queryByText("For you")).not.toBeInTheDocument();
    expect(screen.queryByText("P2")).not.toBeInTheDocument();
    expect(
      screen
        .getByText("Reviewers")
        .compareDocumentPosition(screen.getByText("Was this report useful?")) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});
