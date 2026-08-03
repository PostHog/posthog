import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  items: [] as ChannelItemModel[],
  isLoading: false,
  channelMissing: false,
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelItems", () => ({
  useChannelItems: () => ({
    items: mocks.items,
    actions: { open: vi.fn(), togglePin: vi.fn(), archive: vi.fn() },
    me: { uuid: "me-uuid" },
    isLoading: mocks.isLoading,
    channelMissing: mocks.channelMissing,
  }),
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
}));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => vi.fn(),
  useRouterState: () => "/website/channel-1",
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
// stack for. Stubbed at the module boundary, as WebsiteLayout.test.tsx does for
// the same reason.
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [] }),
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

import { ChannelSidebar } from "./ChannelSidebar";

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
    authorName: "Someone else",
    // Not the viewer, so filtering to "Me" leaves nothing.
    authorUuid: "someone-else-uuid",
    templateId: null,
    task: null,
    ...overrides,
  };
}

// A fresh element per render: React bails out of re-rendering an element it has
// already seen by reference, and these tests change the hook's answer between
// renders rather than the props.
const sidebar = () => (
  <Theme>
    <ChannelSidebar channelId="channel-1" />
  </Theme>
);

function renderSidebar() {
  return render(sidebar());
}

describe("ChannelSidebar", () => {
  beforeEach(() => {
    mocks.items = [];
    mocks.isLoading = false;
    mocks.channelMissing = false;
  });

  it.each([
    {
      what: "nothing has arrived yet",
      state: { items: [], isLoading: true },
      shown: [] as string[],
      hidden: ["Sessions", "No matches", "Nothing here yet"],
    },
    {
      what: "the space is settled and genuinely empty",
      state: { items: [], isLoading: false },
      shown: ["Nothing here yet"],
      hidden: ["Sessions", "No matches"],
    },
    {
      what: "the space is settled with items",
      state: { items: [item()], isLoading: false },
      shown: ["Sessions", "Investigate signup drop-off"],
      hidden: ["No matches", "Nothing here yet"],
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
    const user = userEvent.setup();
    mocks.items = [item()];
    const { rerender } = renderSidebar();

    // Filter down to the viewer's own items; this one is someone else's, so the
    // settled list really has no matches.
    await user.click(screen.getByRole("button", { name: "Filter" }));
    await user.click(await screen.findByRole("menuitemradio", { name: "Me" }));
    expect(screen.getByText("No matches")).toBeInTheDocument();

    // Reloading the space empties the list again — that isn't a verdict.
    mocks.items = [];
    mocks.isLoading = true;
    rerender(sidebar());

    expect(screen.queryByText("No matches")).not.toBeInTheDocument();
    expect(screen.queryByText("Nothing here yet")).not.toBeInTheDocument();
  });

  it("shows a single empty state when the last item goes away under a search", async () => {
    const user = userEvent.setup();
    mocks.items = [item()];
    const { rerender } = renderSidebar();

    await user.click(screen.getByRole("button", { name: "Search" }));
    mocks.items = [];
    rerender(sidebar());

    expect(screen.getByText("No matches")).toBeInTheDocument();
    expect(screen.queryByText("Nothing here yet")).not.toBeInTheDocument();
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

  it("lists recents newest first without day separators", () => {
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

    expect(screen.getByText("Today's work")).not.toBeNull();
    expect(screen.getByText("Also today")).not.toBeNull();
    expect(screen.getByText("Yesterday's work")).not.toBeNull();
    expect(screen.getByText("Older work")).not.toBeNull();
    expect(screen.queryByText("Today")).toBeNull();
    expect(screen.queryByText("Yesterday")).toBeNull();
    expect(screen.queryByText("Monday, July 20th")).toBeNull();
  });

  it("keeps items from the same day as plain rows", () => {
    mocks.items = [
      item({ key: "task:a", id: "a", ts: new Date(2026, 6, 29, 9).getTime() }),
      item({ key: "task:b", id: "b", ts: new Date(2026, 6, 29, 8).getTime() }),
      item({ key: "task:c", id: "c", ts: new Date(2026, 6, 29, 1).getTime() }),
    ];

    renderSidebar();

    expect(screen.getAllByText("Investigate signup drop-off")).toHaveLength(3);
    expect(screen.queryByText("Today")).toBeNull();
  });

  it("lists pins in the one session list, ahead of newer items", () => {
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

    // No section of its own — a pin is a mark on a session, and the row's badge
    // is what says so.
    expect(screen.queryByText("Pinned")).toBeNull();
    const titles = screen
      .getAllByText(/Kept at hand|Filed this morning/)
      .map((el) => el.textContent);
    // Older, but pinned: it sorts above the newer row rather than risking the
    // recents cap.
    expect(titles).toEqual(["Kept at hand", "Filed this morning"]);
  });
});
