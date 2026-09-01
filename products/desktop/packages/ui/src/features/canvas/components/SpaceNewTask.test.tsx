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

const {
  track,
  useFolderInstructions,
  useContextLayerFlag,
  useChannelWikiContext,
  taskInputProps,
} = vi.hoisted(() => ({
  track: vi.fn(),
  useFolderInstructions: vi.fn(),
  useContextLayerFlag: vi.fn(),
  useChannelWikiContext: vi.fn(),
  taskInputProps: vi.fn(),
}));

// What the hook returns when the space has no wiki page, so the legacy
// CONTEXT.md is the answer.
const NO_WIKI_PAGE = {
  path: undefined,
  useLegacy: true,
  blocked: false,
  failed: false,
  unavailable: false,
  retry: () => {},
};

// TaskInput is a huge hook-heavy component; stub it down to just the surface
// this test cares about — a button that fires onContextChipClick when wired.
vi.mock("@posthog/ui/features/task-detail/components/TaskInput", () => ({
  TaskInput: (props: {
    allowNoRepo?: boolean;
    onContextChipClick?: () => void;
  }) => {
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

// The raw channel rows SpaceNewTask reads repository defaults from.
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannels", () => ({
  useTaskChannels: () => ({
    channels: [
      {
        id: "chan-1",
        name: "project-bluebird",
        channel_type: "public",
        starred: false,
        repositories: ["PostHog/posthog"],
        github_integration: 7,
      },
    ],
  }),
}));

// SpaceSelect (the spaceSelector chip) reads useChannels; keep its dependency
// chain inert under the stubbed TaskInput.
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: [
      {
        id: "chan-1",
        name: "project-bluebird",
        channelType: "public",
        starred: false,
      },
    ],
  }),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasks", () => ({
  useChannelTaskMutations: () => ({ fileTask: vi.fn() }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useFolderInstructions", () => ({
  useFolderInstructions,
}));
vi.mock("@posthog/ui/features/feature-flags/useContextLayerFlag", () => ({
  useContextLayerFlag,
}));
vi.mock("@posthog/ui/features/context-wiki/hooks/useContextWiki", () => ({
  useChannelWikiContext,
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
      location: { state: { tabId: string } };
    }) => unknown;
  }) =>
    select({
      matches: [
        { routeId: "/spaces/$channelId/new", params: { channelId: "chan-1" } },
      ],
      location: { state: { tabId: "tab-1" } },
    }),
}));

import { useTaskInputPrefillStore } from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import { SpaceNewTask } from "./SpaceNewTask";

function renderNewTask() {
  render(
    <Theme>
      <SpaceNewTask channelId="chan-1" />
    </Theme>,
  );
}

describe("SpaceNewTask context panel", () => {
  beforeEach(() => {
    track.mockReset();
    useFolderInstructions.mockReset();
    useContextLayerFlag.mockReturnValue(false);
    useChannelWikiContext.mockReturnValue(NO_WIKI_PAGE);
    taskInputProps.mockReset();
    useTaskInputPrefillStore.setState({ prefill: {} });
  });

  it("blocks submission while the enabled wiki page is unresolved", () => {
    useContextLayerFlag.mockReturnValue(true);
    useChannelWikiContext.mockReturnValue({
      ...NO_WIKI_PAGE,
      useLegacy: false,
      blocked: true,
    });
    useFolderInstructions.mockReturnValue({
      data: { content: "legacy body" },
    });

    renderNewTask();

    expect(taskInputProps).toHaveBeenLastCalledWith(
      expect.objectContaining({
        channelContext: undefined,
        channelContextBlocked: true,
      }),
    );
  });

  // The decision itself is covered in channelWikiContext.test.ts; this only
  // proves the composer forwards it, so the person is actually told.
  it.each([
    [
      "a retryable failure",
      { blocked: true, failed: true },
      { channelContextBlocked: true, channelContextFailed: true },
    ],
    [
      "a permanent 403",
      { unavailable: true },
      { channelContextUnavailable: true, channelContextBlocked: false },
    ],
  ])(
    "tells the person when the wiki lookup ends in %s",
    (_label, outcome, expectedProps) => {
      useContextLayerFlag.mockReturnValue(true);
      useChannelWikiContext.mockReturnValue({
        ...NO_WIKI_PAGE,
        useLegacy: false,
        ...outcome,
      });
      useFolderInstructions.mockReturnValue({
        data: { content: "legacy body" },
      });

      renderNewTask();

      expect(taskInputProps).toHaveBeenLastCalledWith(
        expect.objectContaining({
          channelContext: undefined,
          ...expectedProps,
        }),
      );
    },
  );

  it("creates the task in the channel's feed", () => {
    useFolderInstructions.mockReturnValue({ data: undefined });
    renderNewTask();

    expect(taskInputProps).toHaveBeenLastCalledWith(
      expect.objectContaining({
        channelId: "chan-1",
        channelContextId: "chan-1",
        sessionId: "task-input:tab-1",
      }),
    );
  });

  // Recovery routes an interrupted prompt through this composer under the
  // channels layout. It must forward the full content (chips + attachments) and
  // the record key, or the prompt lands in an empty composer and the durable
  // record is never cleared.
  it("forwards a recovered prompt's content and record key into the composer", () => {
    useFolderInstructions.mockReturnValue({ data: undefined });
    const initialContent = {
      segments: [
        { type: "text" as const, text: "restore me" },
        {
          type: "chip" as const,
          chip: { type: "file" as const, id: "src/app.ts", label: "app.ts" },
        },
      ],
      attachments: [{ id: "att-1", label: "diagram.png" }],
    };
    useTaskInputPrefillStore.setState({
      prefill: {
        initialContent,
        recoveredFromKey: "pending-key",
        requestId: "req-1",
      },
    });

    renderNewTask();

    expect(taskInputProps).toHaveBeenLastCalledWith(
      expect.objectContaining({
        initialContent,
        recoveredFromKey: "pending-key",
        initialPromptKey: "req-1",
      }),
    );
  });

  it("passes the space's repository defaults so cloud tasks can span repos", () => {
    useFolderInstructions.mockReturnValue({ data: undefined });
    renderNewTask();

    expect(taskInputProps).toHaveBeenLastCalledWith(
      expect.objectContaining({
        allowNoRepo: true,
        channelRepositories: ["PostHog/posthog"],
        channelGithubIntegration: 7,
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
