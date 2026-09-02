import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  navigateToInboxReports: vi.fn(),
}));

vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToInboxReports: mocks.navigateToInboxReports,
}));

import { useActivityFilterStore } from "@posthog/ui/features/canvas/stores/activityFilterStore";
import { useInboxReviewerScopeStore } from "@posthog/ui/features/inbox/stores/inboxReviewerScopeStore";
import { useInboxSignalsFilterStore } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import { InboxActivityOverflowRow } from "./InboxActivityOverflowRow";

describe("InboxActivityOverflowRow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useActivityFilterStore.setState({
      inboxScope: "entire-project",
      inboxSourceProductFilter: ["github"],
      inboxPrFilter: "with_pr",
      inboxSortField: "created_at",
      inboxSortDirection: "desc",
      inboxPriorityFilter: ["P0", "P1"],
    });
    useInboxReviewerScopeStore.setState({ scope: "for-you" });
    useInboxSignalsFilterStore.setState({
      sourceProductFilter: [],
      prFilter: "all",
      sortField: "priority",
      sortDirection: "asc",
      priorityFilter: [],
    });
  });

  it("opens the Reports tab with the Activity inbox filters", () => {
    const onOpened = vi.fn();
    render(<InboxActivityOverflowRow count={4} onOpened={onOpened} />);

    fireEvent.click(screen.getByText("View 4 more reports"));

    expect(useInboxReviewerScopeStore.getState().scope).toBe("entire-project");
    expect(
      useInboxSignalsFilterStore.getState().sourceProductFilter,
    ).toStrictEqual(["github"]);
    expect(useInboxSignalsFilterStore.getState().prFilter).toBe("with_pr");
    expect(useInboxSignalsFilterStore.getState().sortField).toBe("created_at");
    expect(useInboxSignalsFilterStore.getState().sortDirection).toBe("desc");
    expect(useInboxSignalsFilterStore.getState().priorityFilter).toStrictEqual([
      "P0",
      "P1",
    ]);
    expect(mocks.navigateToInboxReports).toHaveBeenCalledOnce();
    expect(onOpened).toHaveBeenCalledOnce();
  });
});
