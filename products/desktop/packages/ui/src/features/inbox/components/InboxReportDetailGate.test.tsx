import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  reportQuery: {
    data: undefined,
    isLoading: true,
    isFetching: true,
    isFetchedAfterMount: false,
  },
}));

vi.mock("@posthog/ui/features/inbox/components/DetailBackLink", () => ({
  DetailBackLink: () => null,
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportById: () => mocks.reportQuery,
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxBackTarget", async () => ({
  asInboxBackTarget: () => null,
  useInboxTriageOrigin: () => null,
}));
vi.mock("@posthog/ui/features/inbox/hooks/useReportOpenTracker", () => ({
  useReportOpenTracker: () => undefined,
}));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
}));

import { InboxReportDetailGate } from "./InboxReportDetailGate";

describe("InboxReportDetailGate", () => {
  beforeEach(() => {
    mocks.reportQuery = {
      data: undefined,
      isLoading: true,
      isFetching: true,
      isFetchedAfterMount: false,
    };
  });

  it.each([
    ["while the report loads", true],
    ["when the report is missing", false],
  ])("keeps the fallback action available %s", (_case, isLoading) => {
    mocks.reportQuery = {
      data: undefined,
      isLoading,
      isFetching: isLoading,
      isFetchedAfterMount: !isLoading,
    };

    render(
      <InboxReportDetailGate
        reportId="report-1"
        backTo="/activity"
        backLabel="Back to activity"
        statusRedirect={false}
        missingCopy="Report not found"
        fallbackAction={<button type="button">Close activity item</button>}
      >
        {() => <div>Report</div>}
      </InboxReportDetailGate>,
    );

    expect(screen.getByText("Close activity item")).toBeInTheDocument();
  });
});
