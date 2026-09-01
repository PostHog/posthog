import type { SignalReport } from "@posthog/shared/types";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  activeReports: [] as SignalReport[],
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
  allReportsOptions: null as {
    applySourceFilter?: boolean;
    applySearchFilter?: boolean;
    groupByStatus?: boolean;
    statusFilter?: string;
  } | null,
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
  useInboxAllReports: (options: {
    applySourceFilter?: boolean;
    applySearchFilter?: boolean;
    groupByStatus?: boolean;
    statusFilter?: string;
  }) => {
    mocks.allReportsOptions = options;
    return {
      scopedReports: mocks.activeReports,
      allReports: mocks.activeReports,
      isLoading: false,
      hasNextPage: false,
      isFetchingNextPage: false,
      fetchNextPage: vi.fn(),
      searchQuery: options.applySearchFilter === false ? "" : mocks.searchQuery,
      totalCount: 0,
      scope: "entire_project",
      isSuccess: true,
      sourceProductFilter: [],
      priorityFilter: [],
      prFilter: "all",
    };
  },
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
    resolved: mocks.activeReports.filter(
      (report) => report.status === "resolved",
    ).length,
    dismissed: mocks.activeReports.filter(
      (report) => report.status === "suppressed",
    ).length,
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

vi.mock("@posthog/ui/features/inbox/components/InboxReportContextMenu", () => ({
  InboxReportContextMenu: ({ children }: { children: ReactNode }) => children,
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

vi.mock("@posthog/ui/features/inbox/components/InboxReportFilters", () => ({
  InboxReportFilters: () => null,
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
    mocks.searchQuery = "checkout";
    mocks.triageFocusEnabled = false;
    mocks.triageProps = null;
    mocks.locationState = {};
    mocks.allReportsOptions = null;
    useInboxSignalsFilterStore.setState({
      searchQuery: "checkout",
      sourceProductFilter: [],
      priorityFilter: [],
      reportStateFilter: ["review_and_merge", "needs_decision"],
    });
  });

  it("shows selected terminal states in the same list", () => {
    mocks.activeReports = [
      activeReport("active-report", "Checkout summary"),
      {
        ...archivedReport("resolved-report", "Checkout errors"),
        status: "resolved",
      },
      archivedReport("dismissed-report", "Slow dashboards"),
    ];
    useInboxSignalsFilterStore
      .getState()
      .setReportStateFilter(["needs_decision", "resolved", "dismissed"]);
    render(<ReportsInboxView />);

    expect(screen.getByText("Checkout summary")).toBeInTheDocument();
    expect(screen.getByText("Checkout errors")).toBeInTheDocument();
    expect(screen.getByText("Slow dashboards")).toBeInTheDocument();
    expect(screen.queryByText("Review and merge")).toBeNull();
    expect(screen.queryByText("Resolved and dismissed")).toBeNull();
    expect(mocks.allReportsOptions?.statusFilter).toBe(
      "ready,pending_input,resolved,suppressed",
    );
  });

  it("shows the empty state when no selected reports exist", () => {
    render(<ReportsInboxView />);

    expect(screen.getByText("Nothing to review")).toBeTruthy();
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

  it("shows all loaded reports in one list", () => {
    mocks.activeReports = Array.from({ length: 11 }, (_, index) =>
      activeReport(`report-${index + 1}`, `Report ${index + 1}`),
    );
    mocks.searchQuery = "";

    render(<ReportsInboxView />);

    expect(screen.getByText("Report 1")).toBeInTheDocument();
    expect(screen.getByText("Report 11")).toBeInTheDocument();
    expect(screen.queryByText(/Show more/)).toBeNull();
  });

  it("shows actionable reports in one list and omits pipeline reports", () => {
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

    expect(screen.getByText("Report with PR")).toBeInTheDocument();
    expect(screen.getByText("feat(cohorts)")).toBeInTheDocument();
    expect(screen.getByText("Report without PR")).toBeInTheDocument();
    expect(screen.queryByText("Pipeline report")).toBeNull();
    expect(screen.queryByText("In progress")).toBeNull();
    expect(screen.queryByText(/need a decision/)).toBeNull();
    expect(screen.queryByText("Review")).toBeNull();
    expect(screen.queryByLabelText(/Archive this report/)).toBeNull();
    expect(mocks.allReportsOptions?.applySourceFilter).toBe(false);
    expect(mocks.allReportsOptions?.applySearchFilter).toBe(false);
    expect(mocks.allReportsOptions?.groupByStatus).toBe(false);
    expect(mocks.allReportsOptions?.statusFilter).toBe("ready,pending_input");
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
