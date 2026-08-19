import { Theme } from "@radix-ui/themes";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));
vi.mock("@posthog/ui/hooks/useSetHeaderContent", () => ({
  useSetHeaderContent: vi.fn(),
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelBreadcrumb", () => ({
  ChannelBreadcrumb: () => null,
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelFeedView", () => ({
  ChannelFeedView: ({ intro }: { intro?: ReactNode }) => intro,
}));
vi.mock("@posthog/ui/features/canvas/components/TaskFeedModal", () => ({
  TaskFeedModal: () => null,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useProjectTaskFeeds", () => ({
  useProjectTaskFeed: () => ({
    id: "feed-1",
    projectId: 1,
    ownerId: "user-1",
    name: "Billing work",
    query: "billing",
    createdAt: "2026-08-01T00:00:00Z",
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskFeedResults", () => ({
  useTaskFeedResults: () => ({
    tasks: [],
    isComplete: true,
    isLoading: false,
    issues: [],
  }),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { useTaskFeedsStore } from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { TaskFeedHome } from "./TaskFeedHome";

describe("TaskFeedHome", () => {
  beforeEach(() => {
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
  });

  it("requires confirmation before deleting a saved search", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <TaskFeedHome feedId="feed-1" />
      </Theme>,
    );

    await user.click(screen.getByText("Delete…"));
    expect(useTaskFeedsStore.getState().feeds).toHaveLength(1);

    const dialog = screen.getByRole("alertdialog");
    expect(
      within(dialog).getByText("Delete saved search?"),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByText("Delete"));

    expect(useTaskFeedsStore.getState().feeds).toEqual([]);
  });
});
