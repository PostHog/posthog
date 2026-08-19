import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/canvas/hooks/useTaskFeedResults", () => ({
  useFeedQueryPlan: () => ({ plan: undefined }),
  useTaskFeedResults: () => ({
    tasks: [{ id: "task-1" }],
    isComplete: true,
    isLoading: false,
    issues: [],
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
  it("hides stale preview results when the query is empty", () => {
    render(
      <Theme>
        <TaskFeedModal open onOpenChange={vi.fn()} />
      </Theme>,
    );

    expect(screen.queryByText("1 task matches")).not.toBeInTheDocument();
  });
});
