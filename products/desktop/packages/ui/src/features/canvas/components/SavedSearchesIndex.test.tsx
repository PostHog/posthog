import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigate = vi.fn();
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => navigate }));
vi.mock("@posthog/ui/hooks/useSetHeaderContent", () => ({
  useSetHeaderContent: vi.fn(),
}));
vi.mock("@posthog/ui/features/canvas/components/FeedQueryHighlight", () => ({
  FeedQueryHighlight: ({ query }: { query: string }) => <span>{query}</span>,
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: vi.fn() },
}));
vi.mock("@posthog/ui/features/canvas/hooks/useProjectTaskFeeds", () => ({
  useProjectTaskFeeds: () => useTaskFeedsStore.getState().feeds,
}));

import { useTaskFeedsStore } from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { SavedSearchesIndex } from "./SavedSearchesIndex";

describe("SavedSearchesIndex", () => {
  beforeEach(() => {
    navigate.mockClear();
  });

  it("shows the empty state when there are no saved searches", () => {
    useTaskFeedsStore.setState({ feeds: [] });
    render(
      <Theme>
        <SavedSearchesIndex />
      </Theme>,
    );
    expect(screen.getByText("No saved searches yet")).toBeInTheDocument();
  });

  it("lists saved searches and navigates to one on click", async () => {
    useTaskFeedsStore.setState({
      feeds: [
        {
          id: "feed-1",
          projectId: 1,
          ownerId: "user-1",
          name: "Billing work",
          query: "billing",
          createdAt: "2026-08-01T00:00:00Z",
        },
      ],
    });
    const user = userEvent.setup();
    render(
      <Theme>
        <SavedSearchesIndex />
      </Theme>,
    );

    await user.click(screen.getByText("Billing work"));
    expect(navigate).toHaveBeenCalledWith({
      to: "/feeds/$feedId",
      params: { feedId: "feed-1" },
    });
  });
});
