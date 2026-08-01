import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { formatRelativeTimeShort } from "@posthog/shared";
import type { TaskStatusInput } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The row's status comes from live session/workspace state and a per-task tRPC
// query, none of which a unit test has. Stubbed at the module boundary, as
// ChannelSidebar.test.tsx does for the same reason.
const mocks = vi.hoisted(() => ({ status: null as TaskStatusInput | null }));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTaskStatus", () => ({
  useChannelTaskStatus: () => mocks.status,
}));
// The row menu's spaces list and filing mutation are tRPC-backed.
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [{ id: "channel-1", name: "code" }] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useFileTaskToChannel", () => ({
  useFileTaskToChannel: () => vi.fn(),
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));

import { usePendingCanvasDeleteStore } from "@posthog/ui/features/canvas/stores/pendingCanvasDeleteStore";
import { ChannelItemRow } from "./ChannelItemRow";

const actions = {
  open: () => {},
  togglePin: () => {},
  archive: () => {},
  remove: () => {},
};

function item(overrides: Partial<ChannelItemModel> = {}): ChannelItemModel {
  return {
    key: "task:task-1",
    kind: "task",
    id: "task-1",
    title: "Investigate signup drop-off",
    ts: Date.parse("2026-07-17T12:00:00.000Z"),
    pinned: false,
    rawStatus: null,
    authorUser: null,
    authorName: null,
    authorUuid: "user-uuid",
    templateId: null,
    task: null,
    ...overrides,
  };
}

function renderRow(model: ChannelItemModel) {
  return render(
    <Theme>
      <ChannelItemRow actions={actions} isActive={false} item={model} />
    </Theme>,
  );
}

beforeEach(() => {
  mocks.status = null;
  usePendingCanvasDeleteStore.setState({ pending: {} });
});

describe("ChannelItemRow", () => {
  // The dot vocabulary in one table: what the row's leading mark says for each
  // state a task can be in. Only the states a reader can act on get a voice —
  // run mechanics (queued, failed) resolve to a dot that describes the work
  // rather than the status: starting, live but stalled, or something to read.
  it.each([
    [
      "a permission prompt",
      { needsPermission: true },
      "Needs permission — blocked on you",
    ],
    ["a streaming agent", { isGenerating: true }, "Working"],
    [
      // The run says in_progress, but nothing is streaming: a local run never
      // gets a terminal status written, and the cloud one holds in_progress past
      // the agent. Live, but not moving — the still dot, not the spinner.
      "a run claiming progress with nothing in flight",
      { taskRunStatus: "in_progress" as const },
      "Pending — no work in flight",
    ],
    [
      // Launching: a sandbox is being claimed and the backend leaves this state
      // on its own, so the motion is honest.
      "a queued cloud run",
      { taskRunStatus: "queued" as const, workspaceMode: "cloud" as const },
      "Starting",
    ],
    [
      // A local run's status is never advanced, so queued here means "was
      // launched at some point", not "is starting". Seen parked for hours.
      "a local run parked at queued",
      { taskRunStatus: "queued" as const },
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
      { taskRunStatus: "in_progress" as const, prState: "open" as const },
      "All caught up",
    ],
    [
      "a run whose PR url is known but state isn't",
      {
        taskRunStatus: "in_progress" as const,
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

    expect(screen.getByRole("img", { name: "Cloud" })).not.toBeNull();
    expect(screen.getByRole("img", { name: "Merged" })).not.toBeNull();
    expect(screen.queryByText(formatRelativeTimeShort(item().ts))).toBeNull();
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
    mocks.status = { workspaceMode: "cloud" };

    renderRow(item({ pinned: true }));

    expect(screen.getByRole("img", { name: "Pinned" })).not.toBeNull();
    expect(screen.getByRole("img", { name: "Cloud" })).not.toBeNull();
  });

  it("leaves an unpinned row without one", () => {
    renderRow(item());

    expect(screen.queryByRole("img", { name: "Pinned" })).toBeNull();
  });

  // The hover card and right-click render the same item list from one
  // definition, so both are asserted against the same expectations.
  const MENU_ITEMS = [
    "Pin",
    "Rename",
    "Add to Command Center",
    "File to…",
    "Archive",
  ];

  function renderWithMenu(overrides: {
    onRename?: () => void;
    onAddToCommandCenter?: () => void;
  }) {
    return render(
      <Theme>
        <ChannelItemRow
          actions={actions}
          isActive={false}
          item={item()}
          onRename={overrides.onRename ?? (() => {})}
          onAddToCommandCenter={overrides.onAddToCommandCenter}
        />
      </Theme>,
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

  it("disables Add to Command Center when there is nowhere to put the task", async () => {
    renderWithMenu({ onAddToCommandCenter: undefined });

    await openCard();

    // Quill keeps a disabled button focusable, so the state is aria-disabled
    // rather than the native attribute.
    expect(
      screen.getByRole("button", { name: "Add to Command Center" }),
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

  it("gives a canvas the actions it has: pin and delete, not archive or filing", async () => {
    const canvas = item({
      key: "canvas:c1",
      kind: "canvas",
      id: "c1",
      title: "Web analytics overview",
    });
    render(
      <Theme>
        <ChannelItemRow actions={actions} isActive={false} item={canvas} />
      </Theme>,
    );

    await userEvent.hover(screen.getByText("Web analytics overview"));

    expect(
      await screen.findByRole("button", { name: "Pin" }, { timeout: 2000 }),
    ).not.toBeNull();
    expect(screen.getByRole("button", { name: "Delete…" })).not.toBeNull();
    // A canvas can't be archived, filed to a space, or given a command-centre
    // cell, so those items aren't drawn at all rather than drawn dead.
    for (const absent of ["Archive", "File to…", "Add to Command Center"]) {
      expect(screen.queryByRole("button", { name: absent })).toBeNull();
    }
  });

  it("confirms before deleting a canvas — it goes for the whole space", async () => {
    const remove = vi.fn();
    const canvas = item({
      key: "canvas:c1",
      kind: "canvas",
      id: "c1",
      title: "Web analytics overview",
    });
    render(
      <Theme>
        <ChannelItemRow
          actions={{ ...actions, remove }}
          isActive={false}
          item={canvas}
        />
      </Theme>,
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
});
