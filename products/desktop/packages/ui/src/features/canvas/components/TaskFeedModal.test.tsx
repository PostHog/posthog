import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

let taskQueryCanRetry = true;
let taskQueryError: Error | null = null;
let taskQueryErrorMessage: string | null = null;
const refetch = vi.fn();

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { uuid: "user-1" } }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskFeedResults", () => ({
  useFeedQueryPlan: () => ({ plan: undefined }),
  useTaskFeedResults: () => ({
    tasks: [{ id: "task-1" }],
    canRetry: taskQueryCanRetry,
    error: taskQueryError,
    errorMessage: taskQueryErrorMessage,
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
    taskQueryCanRetry = true;
    taskQueryError = null;
    taskQueryErrorMessage = null;
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
    taskQueryErrorMessage = "Couldn't load matching tasks. Try again.";
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

  it("explains when member lookup cannot verify the query", () => {
    taskQueryCanRetry = false;
    taskQueryError = new Error("Member lookup incomplete");
    taskQueryErrorMessage =
      "Organization member lookup is incomplete. This search cannot verify every teammate.";
    render(
      <Theme>
        <TaskFeedModal
          open
          initialQuery="created-by:alex"
          onOpenChange={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.getByText(taskQueryErrorMessage)).toBeInTheDocument();
    expect(screen.queryByText("Try again")).not.toBeInTheDocument();
  });
});
