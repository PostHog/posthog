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

const { track, useFolderInstructions, taskInputProps } = vi.hoisted(() => ({
  track: vi.fn(),
  useFolderInstructions: vi.fn(),
  taskInputProps: vi.fn(),
}));

// TaskInput is a huge hook-heavy component; stub it down to just the surface
// this test cares about — a button that fires onContextChipClick when wired.
vi.mock("@posthog/ui/features/task-detail/components/TaskInput", () => ({
  TaskInput: (props: { onContextChipClick?: () => void }) => {
    taskInputProps(props);
    return (
      <button
        type="button"
        disabled={!props.onContextChipClick}
        onClick={props.onContextChipClick}
      >
        context-chip
      </button>
    );
  },
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: [{ id: "chan-1", name: "project-bluebird" }],
  }),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasks", () => ({
  useChannelTaskMutations: () => ({ fileTask: vi.fn() }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannels", () => ({
  useBackendChannel: () => ({
    channel: { id: "backend-channel-1", name: "project-bluebird" },
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useFolderInstructions", () => ({
  useFolderInstructions,
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track }));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ setQueryData: vi.fn() }),
}));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
  // The view reads the matched route so it can pass new-task prefill through.
  useRouterState: ({
    select,
  }: {
    select: (s: {
      matches: { routeId: string; params: Record<string, string> }[];
    }) => unknown;
  }) =>
    select({
      matches: [
        { routeId: "/website/$channelId/new", params: { channelId: "chan-1" } },
      ],
    }),
}));

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
    taskInputProps.mockReset();
  });

  it("creates the task in the channel's backend feed", () => {
    useFolderInstructions.mockReturnValue({ data: undefined });
    renderNewTask();

    expect(taskInputProps).toHaveBeenLastCalledWith(
      expect.objectContaining({
        channelId: "backend-channel-1",
        channelContextId: "chan-1",
      }),
    );
  });

  it("opens the context panel and tracks view_context when the chip is clicked", async () => {
    const user = userEvent.setup();
    useFolderInstructions.mockReturnValue({
      data: { content: "# Space context\n\nBackground." },
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
