import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Radix's ScrollArea (in the context panel) observes resizes; jsdom lacks it.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

const { track, useFolderInstructions } = vi.hoisted(() => ({
  track: vi.fn(),
  useFolderInstructions: vi.fn(),
}));

// TaskInput is a huge hook-heavy component; stub it down to just the surface
// this test cares about — a button that fires onContextChipClick when wired.
vi.mock("@posthog/ui/features/task-detail/components/TaskInput", () => ({
  TaskInput: ({ onContextChipClick }: { onContextChipClick?: () => void }) => (
    <button
      type="button"
      disabled={!onContextChipClick}
      onClick={onContextChipClick}
    >
      context-chip
    </button>
  ),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: [{ id: "chan-1", name: "project-bluebird" }],
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasks", () => ({
  useChannelTaskMutations: () => ({ fileTask: vi.fn() }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useFolderInstructions", () => ({
  useFolderInstructions,
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track }));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ setQueryData: vi.fn() }),
}));
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));

import { WebsiteNewTask } from "./WebsiteNewTask";

function renderNewTask() {
  render(
    <Theme>
      <WebsiteNewTask channelId="chan-1" />
    </Theme>,
  );
}

describe("WebsiteNewTask context panel", () => {
  beforeEach(() => {
    track.mockReset();
    useFolderInstructions.mockReset();
  });

  it("opens the context panel and tracks view_context when the chip is clicked", async () => {
    const user = userEvent.setup();
    useFolderInstructions.mockReturnValue({
      data: { content: "# Channel context\n\nBackground." },
    });
    renderNewTask();

    // Panel starts closed.
    expect(
      screen.queryByText("project-bluebird CONTEXT.md"),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "context-chip" }));

    expect(screen.getByText("project-bluebird CONTEXT.md")).toBeInTheDocument();
    const viewContextCalls = () =>
      track.mock.calls.filter(
        ([, props]) => props?.action_type === "view_context",
      );
    expect(viewContextCalls()).toHaveLength(1);
    expect(viewContextCalls()[0][1]).toEqual(
      expect.objectContaining({
        action_type: "view_context",
        surface: "new_task",
        channel_id: "chan-1",
      }),
    );

    // Clicking again closes the panel and must NOT re-track view_context.
    await user.click(screen.getByRole("button", { name: "context-chip" }));
    expect(
      screen.queryByText("project-bluebird CONTEXT.md"),
    ).not.toBeInTheDocument();
    expect(viewContextCalls()).toHaveLength(1);
  });

  it("leaves the chip non-interactive when the channel has no CONTEXT.md", () => {
    useFolderInstructions.mockReturnValue({ data: undefined });
    renderNewTask();
    expect(screen.getByRole("button", { name: "context-chip" })).toBeDisabled();
  });
});
