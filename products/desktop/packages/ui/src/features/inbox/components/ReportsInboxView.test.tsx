import type { SignalReport } from "@posthog/shared/types";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  activeReports: [] as SignalReport[],
  archivedReports: [] as SignalReport[],
  fetchNextPage: vi.fn(),
  navigateToInboxReportDetail: vi.fn(),
  prefetchReport: vi.fn(),
  prefetchRoute: vi.fn(),
  searchQuery: "",
}));

vi.mock("@posthog/ui/features/feature-flags/useTriageFocusEnabled", () => ({
  useTriageFocusEnabled: () => false,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxAllReports", () => ({
  useInboxAllReports: () => ({
    scopedReports: mocks.activeReports,
    allReports: mocks.activeReports,
    isLoading: false,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
    searchQuery: mocks.searchQuery,
    totalCount: 0,
    scope: "entire_project",
    isSuccess: true,
    sourceProductFilter: [],
    priorityFilter: [],
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReports", () => ({
  useInboxReportsInfinite: () => ({
    allReports: mocks.archivedReports,
    isLoading: false,
    hasNextPage: true,
    fetchNextPage: mocks.fetchNextPage,
    isFetchingNextPage: false,
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxSectionCounts", () => ({
  useInboxSectionCounts: () => ({
    decision: mocks.activeReports.filter((report) => report.status === "ready")
      .length,
    decisionPr: 0,
    attention: 0,
    inProgress: 0,
    isLoading: false,
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useTrackReportsInboxViewed", () => ({
  useTrackReportsInboxViewed: () => undefined,
}));

vi.mock(
  "@posthog/ui/features/inbox/hooks/useInboxReportDetailPrefetch",
  () => ({
    useInboxReportDetailPrefetch: () => ({
      prefetch: mocks.prefetchRoute,
      pointerHandlers: {
        onPointerEnter: mocks.prefetchReport,
        onFocus: mocks.prefetchReport,
        onPointerDown: mocks.prefetchReport,
      },
    }),
  }),
);

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToAgents: vi.fn(),
  navigateToInboxReportDetail: mocks.navigateToInboxReportDetail,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReportDismissAction", () => ({
  useInboxReportDismissAction: () => ({
    actionButton: null,
    dialog: null,
  }),
}));

vi.mock(
  "@posthog/ui/features/inbox/components/SuggestedReviewerAvatarStack",
  () => ({ SuggestedReviewerAvatarStack: () => null }),
);

vi.mock(
  "@posthog/ui/features/inbox/components/utils/SignalReportPriorityBadge",
  () => ({ SignalReportPriorityBadge: () => null }),
);

vi.mock("@posthog/ui/features/inbox/components/ReportRestoreButton", () => ({
  ReportRestoreButton: () => null,
}));

vi.mock("@posthog/ui/features/inbox/components/InboxSearchFilterBar", () => ({
  InboxSearchFilterBar: () => null,
}));

vi.mock("@posthog/ui/features/inbox/components/InboxScopeSelect", () => ({
  InboxScopeSelect: () => null,
}));

import { ReportsInboxView } from "./ReportsInboxView";

function archivedReport(id: string, title: string): SignalReport {
  return {
    id,
    title,
    summary: null,
    status: "suppressed",
    total_weight: 1,
    signal_count: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    artefact_count: 0,
    implementation_pr_url: null,
  };
}

function activeReport(id: string, title: string): SignalReport {
  return {
    ...archivedReport(id, title),
    status: "ready",
  };
}

describe("ReportsInboxView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.activeReports = [];
    mocks.archivedReports = [
      archivedReport("matching-report", "Checkout errors"),
      archivedReport("hidden-report", "Slow dashboards"),
    ];
    mocks.searchQuery = "checkout";
    useInboxSignalsFilterStore.setState({
      searchQuery: "checkout",
      sourceProductFilter: [],
      priorityFilter: [],
      prFilter: "all",
    });
  });

  it("applies report search to the resolved and archived section", async () => {
    render(<ReportsInboxView />);

    await userEvent.click(screen.getByText("Resolved & archived"));

    expect(screen.getByText("Checkout errors")).toBeInTheDocument();
    expect(screen.queryByText("Slow dashboards")).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.fetchNextPage).toHaveBeenCalledOnce());
  });

  it("opens a report on the first click without preloading its route", async () => {
    mocks.activeReports = [activeReport("first-report", "First report")];
    mocks.searchQuery = "";

    render(<ReportsInboxView />);

    const row = screen.getByText("First report").closest('[role="button"]');
    if (!row) throw new Error("Report row not found");

    await userEvent.click(row);

    expect(mocks.prefetchReport).toHaveBeenCalled();
    expect(mocks.prefetchRoute).not.toHaveBeenCalled();
    expect(mocks.navigateToInboxReportDetail).toHaveBeenCalledOnce();
    expect(mocks.navigateToInboxReportDetail).toHaveBeenCalledWith(
      "first-report",
    );
  });
});
