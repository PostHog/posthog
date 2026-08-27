import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import {
  DEFAULT_CHANNEL_ITEM_FILTERS,
  DEFAULT_CHANNEL_ITEM_GROUPING,
  DEFAULT_CHANNEL_ITEM_SORT,
} from "@posthog/core/canvas/channelItems";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  items: [] as ChannelItemModel[],
  isLoading: false,
  channelMissing: false,
  pathname: "/spaces/channel-1",
  channelReportsFlag: false,
  open: vi.fn(),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelItems", () => ({
  useChannelItems: () => ({
    items: mocks.items,
    actions: { open: mocks.open, togglePin: vi.fn(), archive: vi.fn() },
    me: { uuid: "me-uuid" },
    isLoading: mocks.isLoading,
    channelMissing: mocks.channelMissing,
  }),
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: (flag: string) =>
    flag === "posthog-desktop-channel-reports"
      ? mocks.channelReportsFlag
      : false,
}));
// Reaches for a QueryClient and auth this suite has no stack for.
vi.mock("@posthog/ui/features/inbox/hooks/useOpenInboxReport", () => ({
  useOpenInboxReport: () => vi.fn(),
}));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
  useRouterState: () => mocks.pathname,
}));

// Both mount their own query stacks; this suite is about the list's own
// loading-vs-empty decisions.
vi.mock("@posthog/ui/features/canvas/components/ChannelBackRow", () => ({
  ChannelBackRow: () => null,
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelsFab", () => ({
  ChannelsFab: () => null,
}));

// The row menu's spaces list reaches for a QueryClient the unit test has no
// stack for. Stubbed at the module boundary, as ShellLayout.test.tsx does for
// the same reason.
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [] }),
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { id: 1, email: "u@posthog.com" } }),
}));
vi.mock("@posthog/ui/features/tasks/useTaskMutations", () => ({
  useRenameTask: () => ({ renameTask: vi.fn() }),
}));
vi.mock("@posthog/ui/features/tasks/useTasks", () => ({
  useTasks: () => ({ data: [] }),
}));
// A row's status dot reaches for live session state and a per-task PR query.
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTaskStatus", () => ({
  useChannelTaskStatus: () => null,
}));
// The bulk bar's actions span the archive, pin, and filing query stacks. What
// the bar does has its own suites; this one is about the list's own states.
vi.mock("@posthog/ui/features/sidebar/useSidebarBulkActions", () => ({
  useSidebarBulkActions: () => ({ selectedCount: 0 }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasksRunState", () => ({
  useChannelTasksRunState: () => [],
}));

import { useTaskSelectionStore } from "@posthog/ui/features/sidebar/taskSelectionStore";
import { ChannelSidebar } from "./ChannelSidebar";

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
    authorName: "Someone else",
    // Not the viewer, so filtering to "Me" leaves nothing.
    authorUuid: "someone-else-uuid",
    templateId: null,
    repository: null,
    branch: null,
    task: null,
    ...overrides,
  };
}

// A fresh element per render: React bails out of re-rendering an element it has
// already seen by reference, and these tests change the hook's answer between
// renders rather than the props.
const sidebar = (channelId = "channel-1") => (
  <Theme>
    <ChannelSidebar channelId={channelId} />
  </Theme>
);

function renderSidebar() {
  return render(sidebar());
}

beforeEach(() => {
  useSidebarStore.setState({
    channelItemFilters: DEFAULT_CHANNEL_ITEM_FILTERS,
    channelItemSort: DEFAULT_CHANNEL_ITEM_SORT,
    channelItemGrouping: DEFAULT_CHANNEL_ITEM_GROUPING,
  });
});

describe("ChannelSidebar", () => {
  beforeEach(() => {
    mocks.items = [];
    mocks.isLoading = false;
    mocks.channelMissing = false;
    mocks.pathname = "/spaces/channel-1";
    mocks.channelReportsFlag = false;
  });

  it.each([
    {
      what: "nothing has arrived yet",
      state: { items: [], isLoading: true },
      shown: [] as string[],
      hidden: ["Sessions", "No matches", "No sessions yet"],
    },
    {
      what: "the space is settled and genuinely empty",
      state: { items: [], isLoading: false },
      // The tabs stay, or an empty tab is one you can't leave.
      shown: ["Sessions", "No sessions yet"],
      hidden: ["No matches"],
    },
    {
      what: "the space is settled with items",
      state: { items: [item()], isLoading: false },
      shown: ["Sessions", "Investigate signup drop-off"],
      hidden: ["No matches", "No sessions yet"],
    },
  ])("shows one state when $what", ({ state, shown, hidden }) => {
    mocks.items = state.items;
    mocks.isLoading = state.isLoading;

    const { container } = renderSidebar();

    for (const text of shown) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    for (const text of hidden) {
      expect(screen.queryByText(text)).not.toBeInTheDocument();
    }
    expect(
      container.querySelector("[aria-busy]")?.getAttribute("aria-busy"),
    ).toBe(String(state.isLoading));
  });

  it("doesn't call a cold load 'no matches' while a filter is active", async () => {
    // A submenu is `pointer-events: none` until Base UI settles it, which never
    // happens under jsdom's layout — the same setup the other menu suites use.
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.items = [item()];
    const { rerender } = renderSidebar();

    // Filter down to the viewer's own items; this one is someone else's, so the
    // settled list really has no matches.
    await user.click(screen.getByRole("button", { name: "Filter" }));
    await user.click(
      await screen.findByRole("menuitem", { name: /Created by/ }),
    );
    // A pointer sequence inside an unsettled submenu never reaches Base UI's
    // handler under jsdom; the reasoning-menu suite picks its radios this way
    // for the same reason.
    fireEvent.click(await screen.findByRole("menuitemradio", { name: "Me" }));
    expect(await screen.findByText("No matches")).toBeInTheDocument();

    // Reloading the space empties the list again — that isn't a verdict.
    mocks.items = [];
    mocks.isLoading = true;
    rerender(sidebar());

    expect(screen.queryByText("No matches")).not.toBeInTheDocument();
    expect(screen.queryByText("No sessions yet")).not.toBeInTheDocument();
  });

  it("gives up a source filter the space you moved to has none of", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.items = [
      item({
        key: "task:slack",
        id: "slack",
        title: "Filed from Slack",
        source: "slack",
      }),
      item({ key: "task:local", id: "local", title: "Started here" }),
    ];
    const { rerender } = renderSidebar();

    await user.click(screen.getByRole("button", { name: "Filter" }));
    await user.click(await screen.findByRole("menuitem", { name: /Source/ }));
    fireEvent.click(
      await screen.findByRole("menuitemradio", { name: "Slack" }),
    );
    expect(screen.queryByText("Started here")).not.toBeInTheDocument();

    // A space with no Slack sessions: the option that narrowed the list is no
    // longer in the menu, so the filter must not be what empties it.
    mocks.items = [
      item({ key: "task:other", id: "other", title: "Somewhere else" }),
    ];
    rerender(sidebar());

    expect(screen.getByText("Somewhere else")).toBeInTheDocument();
    expect(screen.queryByText("No matches")).not.toBeInTheDocument();
  });

  it("keeps a chosen filter across a remount", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.items = [
      item({
        key: "task:slack",
        id: "slack",
        title: "Filed from Slack",
        source: "slack",
      }),
      item({ key: "task:local", id: "local", title: "Started here" }),
    ];
    const { unmount } = renderSidebar();

    await user.click(screen.getByRole("button", { name: "Filter" }));
    await user.click(await screen.findByRole("menuitem", { name: /Source/ }));
    fireEvent.click(
      await screen.findByRole("menuitemradio", { name: "Slack" }),
    );
    expect(screen.queryByText("Started here")).not.toBeInTheDocument();

    // A space switch remounts the list; the narrowing is the user's, not the
    // list's, so it has to come back with it.
    unmount();
    renderSidebar();

    expect(screen.getByText("Filed from Slack")).toBeInTheDocument();
    expect(screen.queryByText("Started here")).not.toBeInTheDocument();
  });

  it("shows a single empty state when the last item goes away under a search", async () => {
    const user = userEvent.setup();
    mocks.items = [item()];
    const { rerender } = renderSidebar();

    await user.click(screen.getByRole("button", { name: "Search" }));
    mocks.items = [];
    rerender(sidebar());

    expect(screen.getByText("No matches")).toBeInTheDocument();
    expect(screen.queryByText("No sessions yet")).not.toBeInTheDocument();
  });

  it("opens a space on its sessions, whichever tab the last one was left on", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.items = [item()];
    const { rerender } = renderSidebar();

    await user.click(screen.getByRole("tab", { name: "Canvases" }));
    expect(screen.getByRole("tab", { name: "Canvases" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    // The pane stays mounted across a space switch, so the tab has to be put
    // back rather than left where the last space was.
    rerender(sidebar("channel-2"));

    expect(screen.getByRole("tab", { name: "Sessions" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows one kind at a time, and drops the run filters with the sessions", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    mocks.items = [
      item(),
      item({
        key: "canvas:c1",
        kind: "canvas",
        id: "c1",
        title: "Signup funnel canvas",
      }),
    ];
    renderSidebar();

    await user.click(screen.getByRole("tab", { name: "Canvases" }));

    expect(screen.getByText("Signup funnel canvas")).toBeInTheDocument();
    expect(
      screen.queryByText("Investigate signup drop-off"),
    ).not.toBeInTheDocument();

    // A canvas has no run, so the filters that ask about one are gone rather
    // than left to empty the tab.
    await user.click(screen.getByRole("button", { name: "Filter" }));
    expect(
      await screen.findByRole("menuitem", { name: /Pinned/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /Status/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Source/ })).toBeNull();
  });
});

describe("ChannelSidebar recents list", () => {
  const NOW = new Date(2026, 6, 29, 12);

  beforeEach(() => {
    mocks.isLoading = false;
    mocks.channelMissing = false;
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("heads each run of days with the day it is", () => {
    mocks.items = [
      item({
        key: "task:a",
        id: "a",
        title: "Today's work",
        ts: new Date(2026, 6, 29, 9).getTime(),
      }),
      item({
        key: "task:b",
        id: "b",
        title: "Also today",
        ts: new Date(2026, 6, 29, 8).getTime(),
      }),
      item({
        key: "task:c",
        id: "c",
        title: "Yesterday's work",
        ts: new Date(2026, 6, 28, 17).getTime(),
      }),
      item({
        key: "task:d",
        id: "d",
        title: "Older work",
        ts: new Date(2026, 6, 20, 17).getTime(),
      }),
    ];

    renderSidebar();

    // The two same-day rows share one header rather than each getting their own.
    const labelled = screen
      .getAllByText(
        /^(Today|Yesterday|Jul 20|Today's work|Also today|Yesterday's work|Older work)$/,
      )
      .map((el) => el.textContent);
    expect(labelled).toEqual([
      "Today",
      "Today's work",
      "Also today",
      "Yesterday",
      "Yesterday's work",
      "Jul 20",
      "Older work",
    ]);
  });

  it("leads with a pinned section, ahead of newer items", () => {
    mocks.items = [
      item({
        key: "task:newer",
        id: "newer",
        title: "Filed this morning",
        ts: new Date(2026, 6, 30, 9).getTime(),
      }),
      item({
        key: "task:pinned",
        id: "pinned",
        title: "Kept at hand",
        pinned: true,
        ts: new Date(2026, 6, 20, 9).getTime(),
      }),
    ];

    renderSidebar();

    // Older, but pinned: it sorts above the newer row rather than risking the
    // recents cap, and it is listed under the pins rather than under its day.
    const listed = screen
      .getAllByText(/^(Pinned|Today|Kept at hand|Filed this morning)$/)
      .map((el) => el.textContent);
    expect(listed).toEqual([
      "Pinned",
      "Kept at hand",
      "Today",
      "Filed this morning",
    ]);
    // The header says it for the whole section, so the rows below drop the badge.
    expect(screen.queryByRole("img", { name: "Pinned" })).toBeNull();
  });
});

describe("ChannelSidebar multi-select", () => {
  beforeEach(() => {
    mocks.isLoading = false;
    mocks.channelMissing = false;
    mocks.pathname = "/spaces/channel-1";
    mocks.open.mockClear();
    useTaskSelectionStore.setState({
      selectedTaskIds: [],
      lastClickedId: null,
    });
    mocks.items = [
      item({ key: "task:a", id: "a", title: "First session" }),
      item({ key: "task:b", id: "b", title: "Second session" }),
      item({ key: "canvas:c", kind: "canvas", id: "c", title: "A canvas" }),
    ];
  });

  it("opens a session on a plain click", async () => {
    const user = userEvent.setup();
    renderSidebar();

    await user.click(screen.getByText("First session"));

    expect(mocks.open).toHaveBeenCalledOnce();
    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([]);
  });

  it.each([
    { name: "meta", modifier: "{Meta>}" },
    { name: "ctrl", modifier: "{Control>}" },
  ])("selects rather than opens on $name-click", async ({ modifier }) => {
    const user = userEvent.setup();
    renderSidebar();

    await user.keyboard(modifier);
    await user.click(screen.getByText("First session"));

    expect(mocks.open).not.toHaveBeenCalled();
    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual(["a"]);
  });

  it("selects a range on shift-click", async () => {
    const user = userEvent.setup();
    renderSidebar();

    await user.keyboard("{Meta>}");
    await user.click(screen.getByText("First session"));
    await user.keyboard("{/Meta}{Shift>}");
    await user.click(screen.getByText("Second session"));

    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([
      "a",
      "b",
    ]);
  });

  it("does not style the open session as selected when another session is selected", () => {
    mocks.pathname = "/spaces/channel-1/tasks/a";
    useTaskSelectionStore.setState({ selectedTaskIds: ["b"] });

    renderSidebar();

    const openRow = screen.getByText("First session").closest("button");
    const selectedRow = screen.getByText("Second session").closest("button");
    expect(openRow).toHaveAttribute("data-active", "true");
    expect(openRow).not.toHaveAttribute("data-in-selection");
    expect(selectedRow).toHaveAttribute("data-in-selection", "true");
  });

  // A canvas can't be archived, filed, or tiled like a session, so it stays out
  // of the selection and modifier-clicking one just opens it.
  it("opens a canvas even on a modifier-click", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    renderSidebar();

    // Canvases are their own tab, so the row has to be brought into view first.
    await user.click(screen.getByRole("tab", { name: "Canvases" }));
    await user.keyboard("{Meta>}");
    await user.click(screen.getByText("A canvas"));

    expect(mocks.open).toHaveBeenCalledOnce();
    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([]);
  });

  it("drops ids that leave the list", async () => {
    const user = userEvent.setup();
    const { rerender } = renderSidebar();
    await user.keyboard("{Meta>}");
    await user.click(screen.getByText("Second session"));
    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual(["b"]);

    mocks.items = [item({ key: "task:a", id: "a", title: "First session" })];
    rerender(sidebar());

    expect(useTaskSelectionStore.getState().selectedTaskIds).toEqual([]);
  });
});
