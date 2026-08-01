import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

// The row context menu's hooks reach for a QueryClient and the DI container,
// neither of which a unit test has. Stubbed at the module boundary, as
// WebsiteLayout.test.tsx does for the same reason.
vi.mock("@posthog/ui/features/tasks/useTaskContextMenu", () => ({
  useTaskContextMenu: () => ({
    showContextMenu: vi.fn(),
    editingTaskId: null,
    setEditingTaskId: vi.fn(),
  }),
}));
vi.mock("@posthog/ui/features/tasks/useTaskMutations", () => ({
  useRenameTask: () => ({ renameTask: vi.fn() }),
}));
vi.mock("@posthog/ui/features/tasks/useTasks", () => ({
  useTasks: () => ({ data: [] }),
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
      hidden: ["Recent", "No matches", "Nothing here yet"],
    },
    {
      what: "the space is settled and genuinely empty",
      state: { items: [], isLoading: false },
      shown: ["Nothing here yet"],
      hidden: ["Recent", "No matches"],
    },
    {
      what: "the space is settled with items",
      state: { items: [item()], isLoading: false },
      shown: ["Recent", "Investigate signup drop-off"],
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
