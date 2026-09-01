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
  triageFocusEnabled: false,
  triageProps: null as {
    initialReportId?: string;
    onExit: () => void;
  } | null,
  locationState: {} as {
    inboxTriageOrigin?: { reportId: string };
  },
  navigate: vi.fn(),
  allReportsOptions: null as { applySourceFilter?: boolean } | null,
  filterBarProps: null as { showSourceFilter?: boolean } | null,
}));

vi.mock("@posthog/ui/features/feature-flags/useTriageFocusEnabled", () => ({
  useTriageFocusEnabled: () => mocks.triageFocusEnabled,
}));

vi.mock("@tanstack/react-router", () => ({
  useLocation: ({ select }: { select: (location: unknown) => unknown }) =>
    select({ state: mocks.locationState }),
  useNavigate: () => mocks.navigate,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxAllReports", () => ({
  useInboxAllReports: (options: { applySourceFilter?: boolean }) => {
    mocks.allReportsOptions = options;
    return {
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
      prFilter: "all",
    };
  },
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
    reviewAndMerge: mocks.activeReports.filter(
      (report) => report.status === "ready" && !!report.implementation_pr_url,
    ).length,
    needsPr: mocks.activeReports.filter(
      (report) =>
        (report.status === "ready" || report.status === "pending_input") &&
        !report.implementation_pr_url,
    ).length,
    resolved: mocks.archivedReports.length,
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

vi.mock("@posthog/ui/features/inbox/components/ReportTriageFocus", () => ({
  ReportTriageFocus: (props: {
    initialReportId?: string;
    onExit: () => void;
  }) => {
    mocks.triageProps = props;
    return null;
  },
}));

vi.mock("@posthog/ui/features/inbox/components/InboxSearchFilterBar", () => ({
  InboxSearchFilterBar: (props: { showSourceFilter?: boolean }) => {
    mocks.filterBarProps = props;
    return null;
  },
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
    actionability: "immediately_actionable",
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
    mocks.triageFocusEnabled = false;
    mocks.triageProps = null;
    mocks.locationState = {};
    mocks.allReportsOptions = null;
    mocks.filterBarProps = null;
    useInboxSignalsFilterStore.setState({
      searchQuery: "checkout",
      sourceProductFilter: [],
      priorityFilter: [],
    });
  });

  it("applies report search to the resolved and archived section", async () => {
    mocks.activeReports = [activeReport("active-report", "Checkout summary")];
    render(<ReportsInboxView />);

    await userEvent.click(screen.getByText("Resolved"));

    expect(screen.getByText("Checkout errors")).toBeInTheDocument();
    expect(screen.queryByText("Slow dashboards")).not.toBeInTheDocument();
    await waitFor(() => expect(mocks.fetchNextPage).toHaveBeenCalledOnce());
  });

  it("does not show terminal sections when the active inbox is empty", () => {
    render(<ReportsInboxView />);

    expect(screen.getByText("No reports match your filters")).toBeTruthy();
    expect(screen.queryByText("Resolved")).toBeNull();
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

  it("shows five more reports at a time", async () => {
    mocks.activeReports = Array.from({ length: 11 }, (_, index) =>
      activeReport(`report-${index + 1}`, `Report ${index + 1}`),
    );
    mocks.searchQuery = "";

    render(<ReportsInboxView />);

    expect(screen.getByText("Report 5")).toBeInTheDocument();
    expect(screen.queryByText("Report 6")).toBeNull();

    await userEvent.click(screen.getByText("Show more (6)"));

    expect(screen.getByText("Report 10")).toBeInTheDocument();
    expect(screen.queryByText("Report 11")).toBeNull();

    await userEvent.click(screen.getByText("Show more (1)"));

    expect(screen.getByText("Report 11")).toBeInTheDocument();
  });

  it("groups actionable reports by PR state and omits pipeline sections", () => {
    mocks.activeReports = [
      {
        ...activeReport("with-pr", "feat(cohorts): Report with PR"),
        implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
      },
      activeReport("without-pr", "Report without PR"),
      {
        ...activeReport("pipeline", "Pipeline report"),
        status: "in_progress",
      },
    ];
    mocks.searchQuery = "";

    render(<ReportsInboxView />);

    const reviewSection = screen
      .getByText("Review and merge")
      .closest("section");
    const needsPrSection = screen.getByText("Needs a PR").closest("section");

    expect(reviewSection).toHaveTextContent("Report with PR");
    expect(reviewSection).toHaveTextContent("feat(cohorts)");
    expect(reviewSection).not.toHaveTextContent("Report without PR");
    expect(needsPrSection).toHaveTextContent("Report without PR");
    expect(needsPrSection).not.toHaveTextContent("Pipeline report");
    expect(screen.queryByText("In progress")).toBeNull();
    expect(screen.queryByText(/need a decision/)).toBeNull();
    expect(screen.queryByText("Review")).toBeNull();
    expect(screen.queryByLabelText(/Archive this report/)).toBeNull();
    expect(mocks.filterBarProps?.showSourceFilter).toBe(false);
    expect(mocks.allReportsOptions?.applySourceFilter).toBe(false);
  });

  it("returns to the same report in triage mode", () => {
    mocks.activeReports = [
      activeReport("first-report", "First report"),
      activeReport("second-report", "Second report"),
    ];
    mocks.searchQuery = "";
    mocks.triageFocusEnabled = true;
    mocks.locationState = {
      inboxTriageOrigin: { reportId: "second-report" },
    };

    render(<ReportsInboxView />);

    expect(mocks.triageProps?.initialReportId).toBe("second-report");
  });
});
