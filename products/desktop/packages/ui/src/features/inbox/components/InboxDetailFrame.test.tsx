import { FileTextIcon } from "@phosphor-icons/react";
import type { SignalReport } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/inbox/components/DetailBackLink", () => ({
  DetailBackLink: () => null,
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
  it("shows the conventional commit tag beside the report title", () => {
    render(
      <InboxDetailFrame
        report={report}
        backTo="/inbox/reports"
        backLabel="Back to reports"
        fallbackTitle="Untitled report"
        summarySection={{ Icon: FileTextIcon, title: "Summary" }}
        evidenceSection={null}
        showDismiss={false}
      />,
    );

    expect(screen.getByText("feat(dashboards)")).toBeInTheDocument();
    expect(screen.getByText("Add compact legend controls")).toBeInTheDocument();
  });
});
