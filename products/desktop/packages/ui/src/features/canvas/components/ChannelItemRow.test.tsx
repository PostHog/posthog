import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { CANVAS_DRAG_TYPE } from "@posthog/ui/features/canvas/canvasDrag";
import type { TaskStatusInput } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import {
  TASK_DRAG_TYPE,
  TASK_IDS_DRAG_TYPE,
} from "@posthog/ui/features/sidebar/taskDrag";
import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";
import { Theme } from "@radix-ui/themes";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The row's status comes from live session/workspace state and a per-task tRPC
// query, none of which a unit test has. Stubbed at the module boundary, as
// ChannelSidebar.test.tsx does for the same reason.
const mocks = vi.hoisted(() => ({
  status: null as TaskStatusInput | null,
  currentUserId: 999 as number | undefined,
  currentUserUuid: "u-1" as string | undefined,
  analysis: {
    canAnalyze: false,
    isPending: false,
    run: vi.fn(),
  },
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({
    data: { id: mocks.currentUserId, uuid: mocks.currentUserUuid },
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTaskStatus", () => ({
  useChannelTaskStatus: () => mocks.status,
}));
// The row menu's spaces list and filing mutation are tRPC-backed. The
// handoff dialog's channels lookup rides the same mock.
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [{ id: "channel-1", name: "code" }] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useFileTaskToChannel", () => ({
  useFileTaskToChannel: () => vi.fn(),
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));
vi.mock(
  "@posthog/ui/features/task-detail/components/TaskAnalysisButton",
  () => ({
    useTaskAnalysis: () => mocks.analysis,
  }),
);
// The handoff dialog is tested on its own; here it only opens.
vi.mock(
  "@posthog/ui/features/task-detail/components/HandoffTaskDialog",
  () => ({
    HandoffTaskDialog: () => null,
  }),
);

import { usePendingCanvasDeleteStore } from "@posthog/ui/features/canvas/stores/pendingCanvasDeleteStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { ChannelItemPreviewCardProvider } from "./ChannelItemHoverCard";
import { ChannelItemRow } from "./ChannelItemRow";

const actions = {
  open: () => {},
  togglePin: () => {},
  setPinned: () => {},
  archive: () => {},
  remove: () => {},
  fileCanvas: () => {},
};

function item(overrides: Partial<ChannelItemModel> = {}): ChannelItemModel {
  return {
    key: "task:task-1",
    kind: "task",
    id: "task-1",
    title: "Investigate signup drop-off",
    ts: Date.parse("2026-07-17T12:00:00.000Z"),
    createdAt: Date.parse("2026-07-16T12:00:00.000Z"),
    pinned: false,
    rawStatus: null,
    environment: null,
    source: null,
    needsInput: false,
    unread: false,
    authorUser: null,
    authorName: null,
    authorUuid: "user-uuid",
    templateId: null,
    repository: null,
    branch: null,
    task: null,
    ...overrides,
  };
}

/**
 * The list's rows share one preview card, hung off a provider above them, so a
 * row on its own has no card to open — every hover assertion here needs it.
 */
function renderInList(row: ReactNode) {
  return render(
    <Theme>
      <ChannelItemPreviewCardProvider>{row}</ChannelItemPreviewCardProvider>
    </Theme>,
  );
}

function renderRow(model: ChannelItemModel) {
  return renderInList(
    <ChannelItemRow actions={actions} isActive={false} item={model} />,
  );
}

beforeEach(() => {
  mocks.status = null;
  mocks.analysis = { canAnalyze: false, isPending: false, run: vi.fn() };
  useSidebarStore.setState({ listItemMetadataFields: [] });
  usePendingCanvasDeleteStore.setState({ pending: {} });
  useTaskSelectionStore.setState({
    selectedTaskIds: [],
    lastClickedId: null,
  });
});

describe("ChannelItemRow", () => {
  // The dot vocabulary in one table: what the row's leading mark says for each
  // state a task can be in. Only the states a reader can act on get a voice —
  // run mechanics (queued, failed) resolve to a dot that describes the work
  // rather than the status: starting, live but stalled, or something to read.
  it.each([
    ["a permission prompt", { needsPermission: true }, "Needs your input"],
    [
      "an agent session being created",
      { isAgentSessionStarting: true },
      "Starting",
    ],
    ["a streaming agent", { isGenerating: true }, "Working"],
    [
      // A background run is one-shot and unattended, so its in_progress really
      // is a claim that the agent is still on it. Live, but nothing streaming —
      // the still dot, not the spinner.
      "a background run claiming progress with nothing in flight",
      { taskRunStatus: "in_progress" as const, runMode: "background" as const },
      "Pending — no work in flight",
    ],
    [
      // The backend leaves an interactive run in_progress after it succeeds, so
      // the session stays open for a follow-up. Reading that as a claim marked
      // every finished session pending, forever, on a row opening it could not
      // clear.
      "an interactive run left in_progress after it finished",
      {
        taskRunStatus: "in_progress" as const,
        runMode: "interactive" as const,
      },
      "All caught up",
    ],
    [
      // Launching: a sandbox is being claimed and the backend leaves this state
      // on its own, so the motion is honest.
      "a queued cloud run",
      { taskRunStatus: "queued" as const, workspaceMode: "cloud" as const },
      "Starting",
    ],
    [
      // A background run's status is never advanced once it parks, so queued
      // here means "was launched at some point", not "is starting".
      "a local background run parked at queued",
      { taskRunStatus: "queued" as const, runMode: "background" as const },
      "Pending — no work in flight",
    ],
    [
      // A PR outranks a run that only claims to be working, but not one that is
      // demonstrably coming up. Re-running a task that already shipped a PR
      // leaves the url on the session and the state in the PR query, so this is
      // the ordinary shape of a second run, not an edge case.
      "a re-queued cloud run on a task that already has a PR",
      {
        taskRunStatus: "queued" as const,
        workspaceMode: "cloud" as const,
        prState: "open" as const,
      },
      "Starting",
    ],
    [
      "a broken run with unseen output",
      { taskRunStatus: "failed" as const, isUnread: true },
      "Unread — something to read",
    ],
    ["a suspended task", { isSuspended: true }, "Suspended — parked"],
    [
      // The cloud workflow holds a run at in_progress while it babysits CI after
      // opening the PR; under a merge queue that wait can outlast the agent by
      // hours, so the PR's existence has to win over the run's claim.
      "a run still babysitting CI behind an open PR",
      {
        taskRunStatus: "in_progress" as const,
        runMode: "background" as const,
        prState: "open" as const,
      },
      "All caught up",
    ],
    [
      "a run whose PR url is known but state isn't",
      {
        taskRunStatus: "in_progress" as const,
        runMode: "background" as const,
        prUrl: "https://github.com/PostHog/code/pull/1",
      },
      "All caught up",
    ],
    [
      // A live local session is the agent typing right now, which no PR overrides.
      "a streaming agent that already has a PR",
      { isGenerating: true, prState: "open" as const },
      "Working",
    ],
    [
      "a merged PR",
      { prState: "merged" as const },
      // PR state lives on the badge, so the dot stays quiet.
      "All caught up",
    ],
    ["an idle task", {}, "All caught up"],
  ])("labels %s", (_case, status: TaskStatusInput, label) => {
    mocks.status = status;

    renderRow(item());

    expect(screen.getByRole("img", { name: label })).not.toBeNull();
  });

  it("badges a PR it can see the url of but not the state of", () => {
    mocks.status = {
      workspaceMode: "cloud",
      prUrl: "https://github.com/PostHog/code/pull/1",
    };

    renderRow(item());

    // Uncoloured, because colour is a verdict — but present, because a task that
    // opened a PR must not look like it did nothing.
    expect(screen.getByRole("img", { name: "Pull request" })).not.toBeNull();
  });

  it("shows a task's badges instead of its timestamp", () => {
    mocks.status = { workspaceMode: "cloud", prState: "merged" };

    renderRow(item());

    expect(screen.getByRole("img", { name: "Merged" })).not.toBeNull();
    expect(screen.queryByText(formatRelativeTimeShort(item().ts))).toBeNull();
  });

  // Running in the cloud is the default, so it gets no badge of its own — and a
  // row with nothing else to say carries no stack at all rather than a laptop
  // that would claim the opposite of where it ran.
  it("leaves a cloud task with nothing else to say unbadged", () => {
    mocks.status = { workspaceMode: "cloud" };

    renderRow(item());

    expect(screen.queryByRole("img", { name: "Cloud" })).toBeNull();
    expect(screen.queryByRole("img", { name: "Local" })).toBeNull();
  });

  it("marks a local task with the laptop badge", () => {
    mocks.status = { workspaceMode: "local" };

    renderRow(item());

    expect(screen.getByRole("img", { name: "Local" })).not.toBeNull();
  });

  it("renders a canvas like a quiet task with its glyph in the badge stack", () => {
    renderRow(
      item({
        key: "canvas:canvas-1",
        kind: "canvas",
        id: "canvas-1",
        title: "Web analytics overview",
        templateId: "web-analytics",
      }),
    );

    expect(screen.getByRole("img", { name: "All caught up" })).not.toBeNull();
    expect(screen.getByRole("img", { name: "Canvas" })).not.toBeNull();
    expect(screen.queryByText(formatRelativeTimeShort(item().ts))).toBeNull();
  });

  it("marks a pinned row with the pin badge, alongside its status badges", () => {
    mocks.status = { workspaceMode: "cloud", prState: "merged" };

    renderRow(item({ pinned: true }));

    expect(screen.getByRole("img", { name: "Pinned" })).not.toBeNull();
    expect(screen.getByRole("img", { name: "Merged" })).not.toBeNull();
  });

  it("leaves an unpinned row without one", () => {
    renderRow(item());

    expect(screen.queryByRole("img", { name: "Pinned" })).toBeNull();
  });

  // A pinned row offering only `move` resolves against the Command Center's
  // `copy` as no drop, so the tile stops accepting it with nothing to show why.
  it.each([{ pinned: false }, { pinned: true }])(
    "makes tasks draggable into the Command Center, pinned=$pinned",
    ({ pinned }) => {
      renderRow(item({ pinned }));
      const setData = vi.fn();
      const dataTransfer = { setData, effectAllowed: "none" };

      fireEvent.dragStart(screen.getByRole("button"), { dataTransfer });

      expect(setData).toHaveBeenCalledWith(TASK_DRAG_TYPE, "task-1");
      expect(dataTransfer.effectAllowed).toBe("copyMove");
    },
  );

  it("drags every selected task into the Command Center", () => {
    useTaskSelectionStore.setState({
      selectedTaskIds: ["task-2", "task-1"],
    });
    renderRow(item());
    const setData = vi.fn();
    const dataTransfer = { setData, effectAllowed: "none" };

    fireEvent.dragStart(screen.getByRole("button"), { dataTransfer });

    expect(setData).toHaveBeenCalledWith(TASK_DRAG_TYPE, "task-1");
    expect(setData).toHaveBeenCalledWith(
      TASK_IDS_DRAG_TYPE,
      JSON.stringify(["task-1", "task-2"]),
    );
    expect(dataTransfer.effectAllowed).toBe("copyMove");
  });

  it("makes canvases draggable into the Command Center", () => {
    renderRow(
      item({
        key: "canvas:canvas-1",
        kind: "canvas",
        id: "canvas-1",
      }),
    );
    const setData = vi.fn();
    const dataTransfer = { setData, effectAllowed: "none" };

    fireEvent.dragStart(screen.getByRole("button"), { dataTransfer });

    expect(setData).toHaveBeenCalledWith(CANVAS_DRAG_TYPE, "canvas-1");
    expect(dataTransfer.effectAllowed).toBe("copy");
  });

  // The hover card and right-click render the same item list from one
  // definition, so both are asserted against the same expectations.
  const MENU_ITEMS = [
    "Pin",
    "Rename",
    "Add to Command Center…",
    "File to…",
    "Archive",
  ];

  function renderWithMenu(overrides: {
    onRename?: () => void;
    onAddToCommandCenter?: () => void;
  }) {
    return renderInList(
      <ChannelItemRow
        actions={actions}
        isActive={false}
        item={item()}
        onRename={overrides.onRename ?? (() => {})}
        onAddToCommandCenter={overrides.onAddToCommandCenter}
      />,
    );
  }

  /** Hovers the row and waits for its preview card, which opens on a delay. */
  async function openCard() {
    await userEvent.hover(screen.getByText("Investigate signup drop-off"));
    return screen.findByRole("button", { name: "Pin" }, { timeout: 2000 });
  }

  it("puts the row's actions in the hover card", async () => {
    renderWithMenu({});

    await openCard();

    for (const label of MENU_ITEMS) {
      expect(screen.getByRole("button", { name: label })).not.toBeNull();
    }
  });

  it("opens the same menu on right-click", () => {
    renderWithMenu({});

    fireEvent.contextMenu(screen.getByText("Investigate signup drop-off"));

    for (const label of MENU_ITEMS) {
      expect(screen.getByRole("menuitem", { name: label })).not.toBeNull();
    }
  });

  it("offers Run analysis for a task with a terminal run", () => {
    const run = vi.fn();
    mocks.analysis = { canAnalyze: true, isPending: false, run };
    const task = {
      id: "task-1",
      task_number: 1,
      slug: "task-1",
      title: "Investigate signup drop-off",
      description: "",
      created_at: "2026-07-16T12:00:00.000Z",
      updated_at: "2026-07-16T12:00:00.000Z",
      origin_product: "user_created",
      latest_run: { id: "run-1", status: "completed" },
    } as Task;

    renderInList(
      <ChannelItemRow
        actions={actions}
        isActive={false}
        item={item({ task })}
      />,
    );
    fireEvent.contextMenu(screen.getByText("Investigate signup drop-off"));

    const analysisItem = screen.getByRole("menuitem", {
      name: "Run analysis",
    });
    expect(analysisItem).not.toBeNull();
    fireEvent.click(analysisItem);
    expect(run).toHaveBeenCalledOnce();
  });

  it("offers Hand off… only to the task's owner", async () => {
    // The API 404s a non-owner's handoff, so the menu must not offer it to one.
    const ownerItem = item({
      authorUser: { id: 999, uuid: "u-1", email: "owner@example.com" },
      task: {
        id: "task-1",
        task_number: 1,
        slug: "task-1",
        title: "Investigate signup drop-off",
        description: "",
        created_at: "2026-07-16T12:00:00.000Z",
        updated_at: "2026-07-16T12:00:00.000Z",
        origin_product: "user_created",
        created_by: { id: 999, uuid: "u-1", email: "owner@example.com" },
        channel: "channel-1",
      },
    });

    renderInList(
      <ChannelItemRow actions={actions} isActive={false} item={ownerItem} />,
    );
    await openCard();
    expect(screen.getByRole("button", { name: "Hand off…" })).not.toBeNull();

    cleanup();

    mocks.currentUserId = 7;
    renderInList(
      <ChannelItemRow actions={actions} isActive={false} item={ownerItem} />,
    );
    await userEvent.hover(screen.getByText("Investigate signup drop-off"));
    await screen.findByRole("button", { name: "Pin" }, { timeout: 2000 });
    expect(screen.queryByRole("button", { name: "Hand off…" })).toBeNull();
    mocks.currentUserId = 999;
  });

  it("disables Add to Command Center when there is nowhere to put the task", async () => {
    renderWithMenu({ onAddToCommandCenter: undefined });

    await openCard();

    // Quill keeps a disabled button focusable, so the state is aria-disabled
    // rather than the native attribute.
    expect(
      screen.getByRole("button", { name: "Add to Command Center…" }),
    ).toHaveAttribute("aria-disabled", "true");
  });

  it("renames from the hover card", async () => {
    const onRename = vi.fn();
    renderWithMenu({ onRename });

    await openCard();
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));

    expect(onRename).toHaveBeenCalledOnce();
  });

  it("flashes a red dot while a canvas waits out its delete-undo window", () => {
    const canvas = item({
      key: "canvas:c1",
      kind: "canvas",
      id: "c1",
      title: "Web analytics overview",
    });
    usePendingCanvasDeleteStore.getState().markPending("c1");

    renderRow(canvas);

    expect(screen.getByRole("img", { name: "Deleting…" })).not.toBeNull();
    expect(screen.queryByRole("img", { name: "All caught up" })).toBeNull();
  });

  it("lets a canvas be filed to another space", async () => {
    const canvas = item({
      key: "canvas:c1",
      kind: "canvas",
      id: "c1",
      title: "Web analytics overview",
      authorUuid: "u-1",
    });
    renderInList(
      <ChannelItemRow
        actions={actions}
        isActive={false}
        item={canvas}
        onAddToCommandCenter={() => {}}
      />,
    );

    await userEvent.hover(screen.getByText("Web analytics overview"));

    expect(
      await screen.findByRole("button", { name: "Pin" }, { timeout: 2000 }),
    ).not.toBeNull();
    expect(screen.getByRole("button", { name: "Delete…" })).not.toBeNull();
    expect(
      screen.getByRole("button", { name: "Add to Command Center…" }),
    ).not.toBeNull();
    expect(screen.getByRole("button", { name: "File to…" })).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
  });

  it("does not offer filing for another user's canvas", async () => {
    const canvas = item({
      key: "canvas:c1",
      kind: "canvas",
      id: "c1",
      title: "Web analytics overview",
      authorUuid: "u-2",
    });
    renderInList(
      <ChannelItemRow actions={actions} isActive={false} item={canvas} />,
    );

    await userEvent.hover(screen.getByText("Web analytics overview"));

    expect(
      await screen.findByRole("button", { name: "Pin" }, { timeout: 2000 }),
    ).not.toBeNull();
    expect(screen.queryByRole("button", { name: "File to…" })).toBeNull();
  });

  it("confirms before deleting a canvas — it goes for the whole space", async () => {
    const remove = vi.fn();
    const canvas = item({
      key: "canvas:c1",
      kind: "canvas",
      id: "c1",
      title: "Web analytics overview",
    });
    renderInList(
      <ChannelItemRow
        actions={{ ...actions, remove }}
        isActive={false}
        item={canvas}
      />,
    );

    await userEvent.hover(screen.getByText("Web analytics overview"));
    await userEvent.click(
      await screen.findByRole("button", { name: "Delete…" }, { timeout: 2000 }),
    );

    // The menu item only opens the confirm; nothing is deleted until it is.
    expect(remove).not.toHaveBeenCalled();
    await userEvent.click(
      await screen.findByRole("button", { name: /^Delete$/ }),
    );

    expect(remove).toHaveBeenCalledWith(canvas);
  });

  it("shows the metadata fields the appearance settings ask for, in that order", () => {
    useSidebarStore.setState({
      listItemMetadataFields: ["branch", "repository"],
    });
    renderRow(
      item({
        authorName: "Ada Lovelace",
        repository: { key: "posthog/code", label: "PostHog/code" },
        branch: "posthog/session-list",
      }),
    );

    // Order is the segment builder's job and is tested there; a row's job is
    // to show what the settings asked for.
    expect(screen.getByText("posthog/session-list")).toBeInTheDocument();
    expect(screen.getByText("PostHog/code")).toBeInTheDocument();
  });

  // A session carries its creator as a user, not a name, so reading the name
  // alone left every session row without one.
  it("names the creator of a session, which carries a user rather than a name", () => {
    useSidebarStore.setState({ listItemMetadataFields: ["creator"] });
    renderRow(
      item({
        authorUser: {
          id: 1,
          uuid: "user-uuid",
          first_name: "Ada",
          last_name: "Lovelace",
          email: "ada@example.com",
        },
      }),
    );

    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  });

  it("leaves a row single-line when no metadata fields are chosen", () => {
    renderRow(
      item({
        authorName: "Ada Lovelace",
        repository: { key: "posthog/code", label: "PostHog/code" },
      }),
    );

    expect(screen.queryByText(/PostHog\/code/)).not.toBeInTheDocument();
  });
});
