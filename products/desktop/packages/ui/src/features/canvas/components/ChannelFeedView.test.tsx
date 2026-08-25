import type { Task } from "@posthog/shared/domain-types";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({
  Link: ({
    children,
    onClick,
  }: {
    children: React.ReactNode;
    onClick?: () => void;
  }) => (
    <a
      href="/task"
      onClick={(event) => {
        event.preventDefault();
        onClick?.();
      }}
    >
      {children}
    </a>
  ),
}));
const { channelTaskData } = vi.hoisted(() => ({
  channelTaskData: { current: undefined as unknown },
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTaskData", () => ({
  useChannelTaskData: () => channelTaskData.current,
}));
vi.mock("@posthog/ui/features/sidebar/useTaskPrStatus", () => ({
  useTaskPrStatus: () => ({ prState: null }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskThread", () => ({
  useTaskThread: () => ({ messages: [] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead", () => ({
  useMarkTaskActivityRead: () => ({ mutate: vi.fn() }),
}));
vi.mock("@posthog/ui/features/sidebar/usePinnedTasks", () => ({
  usePinnedTasks: () => ({ togglePin: vi.fn() }),
}));
const { archiveTask } = vi.hoisted(() => ({ archiveTask: vi.fn() }));
vi.mock("@posthog/ui/features/archive/useArchiveTask", () => ({
  useArchiveTask: () => ({ archiveTask }),
}));
vi.mock(
  "@posthog/ui/features/sidebar/components/ArchiveRunningTaskDialog",
  () => ({
    ArchiveRunningTaskDialog: ({ open }: { open: boolean }) =>
      open ? <div>Archive running task?</div> : null,
  }),
);
vi.mock("@posthog/ui/features/sessions/components/StopCloudRunDialog", () => ({
  StopCloudRunDialog: ({ open, title }: { open: boolean; title: string }) =>
    open ? <div>{title}</div> : null,
}));
const { archivedTaskIds } = vi.hoisted(() => ({
  archivedTaskIds: { current: new Set<string>() },
}));
vi.mock("@posthog/ui/features/archive/useArchivedTaskIds", () => ({
  useArchivedTaskIds: () => archivedTaskIds.current,
}));
vi.mock("@posthog/ui/features/tasks/useTaskMutations", () => ({
  useRenameTask: () => ({ renameTask: vi.fn() }),
}));
vi.mock("@posthog/ui/features/command-center/commandCenterStore", () => ({
  useCommandCenterStore: (
    selector: (state: { cells: (string | null)[] }) => unknown,
  ) => selector({ cells: [null] }),
}));
vi.mock("@posthog/ui/features/command-center/placeTaskInCommandCenter", () => ({
  placeTaskInCommandCenter: vi.fn(),
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: [{ id: "channel-1", name: "Personal space", starred: false }],
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useFileTaskToChannel", () => ({
  useFileTaskToChannel: () => vi.fn(),
}));
vi.mock("@posthog/ui/features/browser-tabs/TaskTabIcon", () => ({
  TaskTabIcon: () => <span />,
}));
vi.mock("@posthog/ui/primitives/hooks/useInView", () => ({
  useInView: () => [vi.fn(), true],
}));

import { ChannelFeedView, ExpandablePrompt, TaskCard } from "./ChannelFeedView";
import { mergeFeedEntries, stripContextBlocks } from "./channelFeedDisplay";

const task = {
  id: "task-1",
  task_number: 1,
  slug: "task-1",
  title: "Investigate signup drop-off",
  description: "A long prompt that needs to be expanded in the channel feed",
  created_at: "2026-07-17T12:00:00.000Z",
  updated_at: "2026-07-17T12:00:00.000Z",
  origin_product: "user_created",
  created_by: {
    id: 1,
    uuid: "user-1",
    email: "person@example.com",
    first_name: "A",
    last_name: "Person",
  },
} satisfies Task;

afterEach(() => {
  vi.restoreAllMocks();
  archivedTaskIds.current = new Set<string>();
  archiveTask.mockReset();
  channelTaskData.current = undefined;
});

// ExpandablePrompt measures how the prompt wraps to decide where to cut and
// whether to show "more". jsdom does no layout, so simulate a 21px line height
// and a scrollHeight that grows with text length (≈20 chars/line).
function mockLayout(charsPerLine: number) {
  const realGetComputedStyle = window.getComputedStyle;
  vi.spyOn(window, "getComputedStyle").mockImplementation((el, ...rest) => {
    const style = realGetComputedStyle(el, ...rest);
    return new Proxy(style, {
      get(target, prop) {
        if (prop === "lineHeight") return "21px";
        const value = Reflect.get(target, prop);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });
  });
  vi.spyOn(HTMLElement.prototype, "scrollHeight", "get").mockImplementation(
    function (this: HTMLElement) {
      return Math.ceil((this.textContent ?? "").length / charsPerLine) * 21;
    },
  );
}

describe("ChannelFeedView", () => {
  it("announces when tasks are loading", () => {
    const { container } = render(
      <Theme>
        <ChannelFeedView
          channelId="channel-1"
          tasks={[]}
          isLoading
          onOpenTask={vi.fn()}
          onOpenThread={vi.fn()}
        />
      </Theme>,
    );

    expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading tasks");
  });

  it("hides archived tasks from the feed", () => {
    const archived = {
      ...task,
      id: "task-archived",
      title: "Already archived",
    } satisfies Task;
    archivedTaskIds.current = new Set([archived.id]);
    render(
      <Theme>
        <ChannelFeedView
          channelId="channel-1"
          tasks={[task, archived]}
          isLoading={false}
          onOpenTask={vi.fn()}
          onOpenThread={vi.fn()}
        />
      </Theme>,
    );

    expect(screen.queryByText("Already archived")).not.toBeInTheDocument();
    expect(screen.getByText(task.title)).toBeInTheDocument();
  });

  it("shows the kind's empty note, not the channel welcome, when a filter empties the feed", () => {
    render(
      <Theme>
        <ChannelFeedView
          channelId="channel-1"
          tasks={[]}
          reports={[]}
          isLoading={false}
          emptyState={<div>Welcome to space</div>}
          onOpenTask={vi.fn()}
          onOpenThread={vi.fn()}
        />
      </Theme>,
    );

    // A genuinely empty, unfiltered feed still shows the channel welcome.
    expect(screen.getByText("Welcome to space")).toBeInTheDocument();

    // Selecting an empty kind must show its own note, not the welcome screen.
    fireEvent.click(screen.getByText("Reports"));
    expect(
      screen.getByText(
        "No reports here yet. Open the filter to widen the list.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Welcome to space")).not.toBeInTheDocument();
  });

  it.each([
    {
      name: "options menu",
      open: async () => {
        fireEvent.mouseDown(
          screen.getByLabelText(`Options for ${task.title}`),
          { button: 0 },
        );
      },
    },
    {
      name: "context menu",
      open: async () => {
        fireEvent.contextMenu(screen.getByText(task.title));
      },
    },
  ])("offers every task action from the $name", async ({ open }) => {
    render(
      <Theme>
        <ChannelFeedView
          channelId="channel-1"
          tasks={[task]}
          isLoading={false}
          onOpenTask={vi.fn()}
          onOpenThread={vi.fn()}
        />
      </Theme>,
    );

    await open();

    await waitFor(() => expect(screen.getByText("Pin")).toBeInTheDocument());
    for (const label of [
      "Pin",
      "Rename",
      "Add to Command Center…",
      "File to…",
      "Archive",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("closes the options menu when its trigger is pressed again", async () => {
    render(
      <Theme>
        <ChannelFeedView
          channelId="channel-1"
          tasks={[task]}
          isLoading={false}
          onOpenTask={vi.fn()}
          onOpenThread={vi.fn()}
        />
      </Theme>,
    );

    const trigger = screen.getByLabelText(`Options for ${task.title}`);
    fireEvent.mouseDown(trigger, { button: 0 });
    await waitFor(() => expect(screen.getByText("Pin")).toBeInTheDocument());

    fireEvent.mouseDown(trigger, { button: 0 });
    await waitFor(() =>
      expect(screen.queryByText("Pin")).not.toBeInTheDocument(),
    );
  });

  it("opens the archive confirmation for an active task", async () => {
    channelTaskData.current = {
      cloudPrUrl: null,
      isGenerating: true,
      isPinned: false,
      needsPermission: false,
      taskRunEnvironment: "cloud",
      taskRunStatus: "in_progress",
    };
    const user = userEvent.setup();
    render(
      <Theme>
        <ChannelFeedView
          channelId="channel-1"
          tasks={[task]}
          isLoading={false}
          onOpenTask={vi.fn()}
          onOpenThread={vi.fn()}
        />
      </Theme>,
    );

    fireEvent.mouseDown(screen.getByLabelText(`Options for ${task.title}`), {
      button: 0,
    });
    await waitFor(() =>
      expect(screen.getByText("Archive")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("Archive"));

    expect(screen.getByText("Archive running task?")).toBeInTheDocument();
    expect(archiveTask).not.toHaveBeenCalled();
  });

  it("opens the stop confirmation for an active cloud task", async () => {
    channelTaskData.current = {
      cloudPrUrl: null,
      isGenerating: true,
      isPinned: false,
      needsPermission: false,
      taskRunEnvironment: "cloud",
      taskRunStatus: "in_progress",
    };
    const user = userEvent.setup();
    render(
      <Theme>
        <ChannelFeedView
          channelId="channel-1"
          tasks={[task]}
          isLoading={false}
          onOpenTask={vi.fn()}
          onOpenThread={vi.fn()}
        />
      </Theme>,
    );

    fireEvent.mouseDown(screen.getByLabelText(`Options for ${task.title}`), {
      button: 0,
    });
    await waitFor(() =>
      expect(screen.getByText("Stop task")).toBeInTheDocument(),
    );

    await user.click(screen.getByText("Stop task"));

    expect(screen.getByText(`Stop "${task.title}"?`)).toBeInTheDocument();
  });

  it("reports when its task is opened", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <Theme>
        <TaskCard task={task} channelId="channel-1" onOpen={onOpen} />
      </Theme>,
    );

    await user.click(screen.getByText(task.title));

    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("expands a truncated prompt", async () => {
    mockLayout(20);
    const user = userEvent.setup();
    const { container } = render(
      <Theme>
        <ExpandablePrompt lines={2}>{task.description}</ExpandablePrompt>
      </Theme>,
    );

    const prompt = container.querySelector(
      "[data-slot=expandable-prompt]",
    ) as HTMLElement;
    // The visible text is the non-measure child (the measure copy is aria-hidden).
    const visible = Array.from(prompt.children).find(
      (c) => !c.hasAttribute("aria-hidden"),
    ) as HTMLElement;
    const more = screen.getByRole("button", { name: "more" });
    // The toggle sits inside the visible prompt text, inline after the ellipsis —
    // not on a separate line below.
    expect(visible).toContainElement(more);
    expect(visible.textContent).toContain("…");
    expect(visible.textContent).not.toContain(task.description);

    await user.click(more);

    expect(visible.textContent).toContain(task.description);
    expect(screen.getByRole("button", { name: "less" })).toBeInTheDocument();
  });

  it("renders no toggle when the prompt fits", () => {
    mockLayout(1000);
    render(
      <Theme>
        <ExpandablePrompt lines={2}>{task.description}</ExpandablePrompt>
      </Theme>,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  // Guards against injected context wrappers (Slack thread history, channel
  // CONTEXT.md) leaking verbatim into the card's prompt snippet.
  it("strips injected context blocks from prompts", () => {
    const description =
      '<slack_thread_context>\nThread started by someone.\n</slack_thread_context>\n\nfix the flaky test in <channel_context channel="web">context body</channel_context> ci';

    expect(stripContextBlocks(description)).toBe("fix the flaky test in  ci");
  });

  // Guards the feed's direction (newest first, not chat-style oldest first)
  // and the tie-break that keeps a same-timestamp announcement directly under
  // the task card it describes.
  it("merges entries newest-first with announcements under their card", () => {
    const older = {
      ...task,
      id: "task-old",
      created_at: "2026-07-16T12:00:00.000Z",
    };
    const announcement = {
      id: "system-1",
      createdAt: task.created_at,
      text: "Building CONTEXT.md",
    };

    const entries = mergeFeedEntries([older, task], [announcement]);

    expect(entries.map((entry) => entry.id)).toEqual([
      "task-1",
      "system-1",
      "task-old",
    ]);
  });
});
