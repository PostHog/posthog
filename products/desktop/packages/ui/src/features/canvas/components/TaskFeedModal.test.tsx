import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

let taskQueryError: Error | null = null;
const refetch = vi.fn();

vi.mock("@posthog/ui/features/canvas/hooks/useTaskFeedResults", () => ({
  useFeedQueryPlan: () => ({ plan: undefined }),
  useTaskFeedResults: () => ({
    tasks: [{ id: "task-1" }],
    error: taskQueryError,
    isComplete: true,
    isFetching: false,
    isLoading: false,
    issues: [],
    refetch,
  }),
}));
vi.mock("@posthog/ui/primitives/hooks/useDebouncedValue", () => ({
  useDebouncedValue: () => ({ debounced: "billing", isPending: false }),
}));
vi.mock("./FeedQueryInput", () => ({
  FeedQueryInput: () => <input />,
}));

import { TaskFeedModal } from "./TaskFeedModal";

describe("TaskFeedModal", () => {
  afterEach(() => {
    taskQueryError = null;
    refetch.mockClear();
  });

  it("hides stale preview results when the query is empty", () => {
    render(
      <Theme>
        <TaskFeedModal open onOpenChange={vi.fn()} />
      </Theme>,
    );

    expect(screen.queryByText("1 task matches")).not.toBeInTheDocument();
  });

  it("shows task preview failures and lets a person retry", async () => {
    taskQueryError = new Error("Network error");
    const user = userEvent.setup();
    render(
      <Theme>
        <TaskFeedModal open initialQuery="billing" onOpenChange={vi.fn()} />
      </Theme>,
    );

    expect(
      screen.getByText("Couldn't load matching tasks. Try again."),
    ).toBeInTheDocument();
    await user.click(screen.getByText("Try again"));
    expect(refetch).toHaveBeenCalledOnce();
  });
});
