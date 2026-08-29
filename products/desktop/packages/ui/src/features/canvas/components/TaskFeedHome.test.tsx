import { Theme } from "@radix-ui/themes";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let taskResultsError: Error | null = null;
const refetch = vi.fn();

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
    canRetry: true,
    error: taskResultsError,
    errorMessage: taskResultsError
      ? "Couldn't load matching tasks. Try again."
      : null,
    isComplete: true,
    isFetching: false,
    isLoading: false,
    issues: [],
    refetch,
    tasks: [],
  }),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { useTaskFeedsStore } from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { TaskFeedHome } from "./TaskFeedHome";

describe("TaskFeedHome", () => {
  beforeEach(() => {
    taskResultsError = null;
    refetch.mockClear();
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

  it("shows task request failures instead of an empty result", async () => {
    taskResultsError = new Error("Network error");
    const user = userEvent.setup();
    render(
      <Theme>
        <TaskFeedHome feedId="feed-1" />
      </Theme>,
    );

    expect(
      screen.getByText("Couldn't load matching tasks. Try again."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No tasks match this saved search"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByText("Try again"));
    expect(refetch).toHaveBeenCalledOnce();
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
