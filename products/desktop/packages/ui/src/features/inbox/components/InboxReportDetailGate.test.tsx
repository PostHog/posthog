import type { SignalReport } from "@posthog/shared/types";
import { useInboxReportStatusConfirmed } from "@posthog/ui/features/inbox/context/inboxReportStatusContext";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { useInboxReportById, useReportOpenTracker } = vi.hoisted(() => ({
  useInboxReportById: vi.fn(),
  useReportOpenTracker: vi.fn(),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportById,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useReportOpenTracker", () => ({
  useReportOpenTracker,
}));

vi.mock("@posthog/ui/features/inbox/components/DetailBackLink", () => ({
  DetailBackLink: () => null,
}));

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxBackTarget", () => ({
  asInboxBackTarget: () => undefined,
  useInboxTriageOrigin: () => undefined,
}));

import { InboxReportDetailGate } from "./InboxReportDetailGate";

const report: SignalReport = {
  id: "report-1",
  title: "fix(inbox): keep the report on screen",
  summary: "The report body is readable from cache.",
  status: "ready",
  total_weight: 1,
  signal_count: 0,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  artefact_count: 0,
  implementation_pr_url: null,
};

function Body({ report }: { report: SignalReport }): React.JSX.Element {
  const statusConfirmed = useInboxReportStatusConfirmed();
  return (
    <div>
      <h1>{report.title}</h1>
      <button type="button" disabled={!statusConfirmed}>
        Dismiss
      </button>
    </div>
  );
}

function renderGate(): void {
  render(
    <InboxReportDetailGate
      reportId={report.id}
      cachedReport={report}
      backTo="/inbox/reports"
      backLabel="Back to reports"
      missingCopy="This report couldn't be found."
    >
      {(resolved) => <Body report={resolved} />}
    </InboxReportDetailGate>,
  );
}

describe("InboxReportDetailGate", () => {
  beforeEach(() => {
    useInboxReportById.mockReset();
    useReportOpenTracker.mockReset();
  });

  it("keeps a cached report on screen while the post-mount fetch runs", () => {
    useInboxReportById.mockReturnValue({
      data: report,
      isLoading: false,
      isFetching: true,
      isFetchedAfterMount: false,
    });

    renderGate();

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      report.title as string,
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(useReportOpenTracker).toHaveBeenCalledWith(report, "reports");
  });

  it.each([
    { name: "holds the triage actions", fetching: true, disabled: true },
    { name: "releases them once settled", fetching: false, disabled: false },
  ])("$name", ({ fetching, disabled }) => {
    useInboxReportById.mockReturnValue({
      data: report,
      isLoading: false,
      isFetching: fetching,
      isFetchedAfterMount: !fetching,
    });

    renderGate();

    const dismiss = screen.getByRole("button", { name: "Dismiss" });
    expect((dismiss as HTMLButtonElement).disabled).toBe(disabled);
  });
});
