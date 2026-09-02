import type { SignalReport } from "@posthog/shared/types";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  activeReports: [] as SignalReport[],
  sourceConfigs: [{ enabled: true }] as { enabled: boolean }[],
  navigateToAgents: vi.fn(),
  navigateToInboxReportDetail: vi.fn(),
  prefetchReport: vi.fn(),
  prefetchRoute: vi.fn(),
  searchQuery: "",
  triageFocusEnabled: false,
  triageProps: null as {
    initialReportId?: string;
    reports: SignalReport[];
    onExit: () => void;
  } | null,
  locationState: {} as {
    inboxTriageOrigin?: { reportId: string };
  },
  navigate: vi.fn(),
  fetchNextPage: vi.fn(),
  pagedStatus: null as string | null,
  allReportsOptions: [] as {
    applySourceFilter?: boolean;
    applySearchFilter?: boolean;
    groupByStatus?: boolean;
    statusFilter?: string;
    enabled?: boolean;
    hasImplementationPr?: boolean;
    actionabilityFilter?: string;
    withPullRequestCount?: boolean;
  }[],
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
    enabled?: boolean;
    hasImplementationPr?: boolean;
    actionabilityFilter?: string;
    withPullRequestCount?: boolean;
  }) => {
    mocks.allReportsOptions.push(options);
    const statuses = new Set(options.statusFilter?.split(",") ?? []);
    const actionability = new Set(
      options.actionabilityFilter?.split(",") ?? [],
    );
    const reports =
      options.enabled === false
        ? []
        : mocks.activeReports.filter(
            (report) =>
              (statuses.size === 0 || statuses.has(report.status)) &&
              (options.hasImplementationPr === undefined ||
                options.hasImplementationPr ===
                  Boolean(report.implementation_pr_url)) &&
              (actionability.size === 0 ||
                (report.actionability != null &&
                  actionability.has(report.actionability))),
          );
    return {
      scopedReports: reports,
      allReports:
        options.statusFilter === mocks.pagedStatus
          ? Array.from({ length: 400 }, () => reports[0]).filter(Boolean)
          : reports,
      isLoading: false,
      isPending: false,
      isError: false,
      hasNextPage: options.statusFilter === mocks.pagedStatus,
      isFetchingNextPage: false,
      fetchNextPage: mocks.fetchNextPage,
      refetch: vi.fn(),
      searchQuery: options.applySearchFilter === false ? "" : mocks.searchQuery,
      totalCount: reports.length,
      scope: "entire_project",
      isSuccess: true,
      sourceProductFilter: [],
      priorityFilter: [],
      prFilter: "all",
      sortField: "created_at",
      sortDirection: "desc",
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

vi.mock("@posthog/ui/features/inbox/hooks/useSignalSourceConfigs", () => ({
  useSignalSourceConfigs: () => ({
    data: mocks.sourceConfigs,
    isPending: false,
    isSuccess: true,
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
  navigateToAgents: mocks.navigateToAgents,
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
    reports: SignalReport[];
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
    mocks.sourceConfigs = [{ enabled: true }];
    mocks.searchQuery = "checkout";
    mocks.triageFocusEnabled = false;
    mocks.triageProps = null;
    mocks.locationState = {};
    mocks.allReportsOptions = [];
    mocks.pagedStatus = null;
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
    expect(
      mocks.allReportsOptions.map((options) => options.statusFilter),
    ).toEqual(["ready", "ready,pending_input", "resolved,suppressed"]);
  });

  it("offers agent configuration when no reports or agents exist", async () => {
    mocks.sourceConfigs = [];
    render(<ReportsInboxView />);

    expect(screen.getByText("Nothing to review")).toBeTruthy();
    expect(screen.getAllByText("Configure agents")).toHaveLength(1);
    await userEvent.click(screen.getByText("Configure agents"));
    expect(mocks.navigateToAgents).toHaveBeenCalledOnce();
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

  it("lets the user load reports after the automatic paging limit", async () => {
    mocks.activeReports = [
      {
        ...activeReport("with-pr", "Report with PR"),
        implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
      },
    ];
    mocks.pagedStatus = "ready";

    render(<ReportsInboxView />);
    await userEvent.click(screen.getByText("Load more"));

    expect(mocks.fetchNextPage).toHaveBeenCalledOnce();
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
    const reviewQuery = mocks.allReportsOptions[0];
    const decisionQuery = mocks.allReportsOptions[1];
    expect(reviewQuery).toMatchObject({
      statusFilter: "ready",
      hasImplementationPr: true,
      withPullRequestCount: false,
    });
    expect(decisionQuery).toMatchObject({
      statusFilter: "ready,pending_input",
      hasImplementationPr: false,
      actionabilityFilter: "immediately_actionable,requires_human_input",
      withPullRequestCount: false,
    });
    expect(
      mocks.allReportsOptions.every(
        (options) =>
          options.applySourceFilter === false &&
          options.applySearchFilter === false &&
          options.groupByStatus === false,
      ),
    ).toBe(true);
  });

  it("returns to the same report in triage mode", () => {
    mocks.activeReports = [
      {
        ...activeReport("merge-report", "Merge report"),
        implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
      },
      activeReport("second-report", "Second report"),
    ];
    mocks.searchQuery = "";
    mocks.triageFocusEnabled = true;
    mocks.locationState = {
      inboxTriageOrigin: { reportId: "second-report" },
    };

    render(<ReportsInboxView />);

    expect(mocks.triageProps?.initialReportId).toBe("second-report");
    expect(mocks.triageProps?.reports.map((report) => report.id)).toEqual([
      "second-report",
    ]);
  });
});
