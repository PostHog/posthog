import type { SignalReport } from "@posthog/shared/types";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  archivedReports: [] as SignalReport[],
  fetchNextPage: vi.fn(),
  searchQuery: "",
}));

vi.mock("@posthog/ui/features/feature-flags/useTriageFocusEnabled", () => ({
  useTriageFocusEnabled: () => false,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxAllReports", () => ({
  useInboxAllReports: () => ({
    scopedReports: [],
    allReports: [],
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
    decision: 0,
    decisionPr: 0,
    monitoring: 0,
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
      prefetch: () => undefined,
      pointerHandlers: {
        onPointerEnter: () => undefined,
        onFocus: () => undefined,
        onPointerDown: () => undefined,
      },
    }),
  }),
);

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

describe("ReportsInboxView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
});
