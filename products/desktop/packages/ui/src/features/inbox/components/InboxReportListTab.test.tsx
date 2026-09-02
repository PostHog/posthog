import { ReadCvLogoIcon } from "@phosphor-icons/react";
import type { SignalReport } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  reports: [] as SignalReport[],
  hasNextPage: false,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxAllReports", () => ({
  useInboxAllReports: () => ({
    scopedReports: mocks.reports,
    allReports: mocks.reports,
    isLoading: false,
    hasNextPage: mocks.hasNextPage,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
  }),
}));

// The filter bar owns its own data hooks; the empty state is what we assert on.
vi.mock("@posthog/ui/features/inbox/components/InboxSearchFilterBar", () => ({
  InboxSearchFilterBar: () => null,
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxBulkActions", () => ({
  buildSuppressDisabledReasonMap: () => new Map(),
  useInboxBulkActions: () => ({
    snoozeSelected: vi.fn(),
    suppressSelected: vi.fn(),
    isSuppressing: false,
    isSnoozing: false,
    snoozeDisabledReason: null,
  }),
}));

vi.mock("@posthog/ui/features/inbox/hooks/useInboxReportListSelection", () => ({
  useInboxReportListSelection: () => ({
    orderedSelectedIds: [],
    selectedCount: 0,
    isReportSelected: () => false,
    handleReportClick: vi.fn(),
    clearSelection: vi.fn(),
  }),
}));

import { InboxReportListTab } from "@posthog/ui/features/inbox/components/InboxReportListTab";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";

const emptyState = {
  Icon: ReadCvLogoIcon,
  forYouTitle: "No reports for you yet",
  entireProjectTitle: "No reports in the project yet",
  teammateTitle: "No reports for this reviewer yet",
  description: "Reports are what agents surface.",
  noun: "reports",
};

function renderTab() {
  render(
    <InboxReportListTab
      predicate={() => true}
      Card={() => null}
      searchPlaceholder="Search reports…"
      emptyState={emptyState}
    />,
  );
}

describe("InboxReportListTab", () => {
  beforeEach(() => {
    mocks.reports = [];
    mocks.hasNextPage = false;
    useInboxSignalsFilterStore.setState({
      searchQuery: "",
      sourceProductFilter: [],
      priorityFilter: [],
      prFilter: "all",
    });
  });

  it("shows the genuine-empty copy when no filter is active", () => {
    renderTab();

    expect(screen.getByText("No reports for you yet")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Clear filters" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the genuine-empty copy when only a PR filter is set, since this shell ignores it", () => {
    useInboxSignalsFilterStore.getState().setPrFilter("with_pr");
    renderTab();

    expect(screen.getByText("No reports for you yet")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Clear filters" }),
    ).not.toBeInTheDocument();
  });

  it("names filters as the cause and clears them on click", async () => {
    useInboxSignalsFilterStore.getState().setPriorityFilter(["P0"]);
    renderTab();

    expect(
      screen.getByText("No reports match your filters"),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Clear filters" }),
    );

    expect(useInboxSignalsFilterStore.getState().priorityFilter).toEqual([]);
  });
});
