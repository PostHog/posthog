import { Theme } from "@radix-ui/themes";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  channels: [] as {
    id: string;
    name: string;
    channelType: "public" | "personal";
    starred: boolean;
    repositories: string[];
    createdBy: null;
  }[],
  tasks: [] as {
    id: string;
    title: string;
    channel: string;
    updated_at: string;
    authorId?: number;
  }[],
  currentUserId: 999 as number | undefined,
  totals: {} as Record<string, number>,
  unreadSessions: {} as Record<string, number>,
  blockedSessions: {} as Record<string, number>,
  channelsLayout: true,
  navigate: vi.fn(),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => mocks.channelsLayout,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: mocks.channels, isLoading: false }),
  useChannelMutations: () => ({ deleteChannel: vi.fn(), isDeleting: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelStars", () => ({
  useChannelStarToggle: () => ({
    isStarred: false,
    toggleStar: vi.fn(),
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useCreateAndOpenDashboard: () => vi.fn(),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useUnreadChannels", () => ({
  useIsChannelUnread: () => () => false,
}));
// Reads the task list and the viewed timestamps, and the timestamps come over
// tRPC — which this file renders without, like the other data hooks it stubs.
vi.mock("@posthog/ui/features/canvas/hooks/useUnreadSessionCount", () => ({
  useUnreadSessionCount: () => (channelId: string | undefined) =>
    mocks.unreadSessions[channelId ?? ""] ?? 0,
}));
// Reads the live session store and the task list, neither of which this file
// mounts.
vi.mock("@posthog/ui/features/canvas/hooks/useBlockedSessionCount", () => ({
  useBlockedSessionCount: () => (channelId: string | undefined) =>
    mocks.blockedSessions[channelId ?? ""] ?? 0,
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { id: mocks.currentUserId } }),
}));
// The row menu's spaces list and filing mutation are tRPC-backed; the flag
// lookup sits behind a service provider that isn't mounted here.
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useFileTaskToChannel", () => ({
  useFileTaskToChannel: () => ({ fileTask: vi.fn() }),
}));
vi.mock(
  "@posthog/ui/features/task-detail/components/HandoffTaskDialog",
  () => ({
    HandoffTaskDialog: () => null,
  }),
);
vi.mock("@posthog/ui/features/canvas/hooks/useRecentSpaceTasks", () => ({
  NO_TASKS: { items: [], total: 0 },
  usePrefetchSpaceTasks: () => () => undefined,
  useRecentSpaceTasks: (spaceIds: string[]) =>
    new Map(
      spaceIds.map((spaceId) => {
        const items = mocks.tasks
          .filter((task) => task.channel === spaceId)
          .map((task) => ({
            key: `task:${task.id}`,
            kind: "task",
            id: task.id,
            title: task.title,
            ts: Date.parse(task.updated_at),
            pinned: false,
            rawStatus: null,
            authorUser:
              task.authorId != null
                ? {
                    id: task.authorId,
                    uuid: `u-${task.authorId}`,
                    email: "owner@example.com",
                  }
                : null,
            authorName: null,
            authorUuid: null,
            task: task.authorId != null ? { id: task.id } : null,
          }));
        // `total` is what the space holds, not what the tree shows — the tests
        // that exercise "View all" set it above the row count.
        return [
          spaceId,
          { items, total: mocks.totals[spaceId] ?? items.length },
        ];
      }),
    ),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelTaskStatus", () => ({
  useChannelTaskStatus: () => null,
}));
vi.mock(
  "@posthog/ui/features/canvas/hooks/useSpaceTaskActions",
  async (importOriginal) => ({
    ...(await importOriginal<
      typeof import("@posthog/ui/features/canvas/hooks/useSpaceTaskActions")
    >()),
    // The real one is a pin mutation and an archive mutation; the tree's rows
    // only need something to hand their menus.
    useSpaceTaskActions: () => ({
      togglePin: vi.fn(),
      archive: vi.fn(),
      commandCenterAssigner: () => undefined,
    }),
  }),
);
vi.mock("@posthog/ui/features/canvas/components/RenameChannelModal", () => ({
  RenameChannelModal: () => null,
}));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => mocks.navigate,
  useRouterState: () => "/spaces",
}));

import {
  shouldKeepListForRoute,
  showChannelList,
  showChannelPane,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import {
  requestSidebarSearchFocus,
  useSidebarSearchStore,
} from "@posthog/ui/features/canvas/stores/sidebarSearchStore";
import { useSpaceTreeStore } from "@posthog/ui/features/canvas/stores/spaceTreeStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { ChannelsList } from "./ChannelsList";

const ME = {
  id: "me-id",
  name: "me",
  channelType: "personal" as const,
  starred: false,
  repositories: [],
  createdBy: null,
};
const ENG = {
  id: "eng-id",
  name: "engineering",
  channelType: "public" as const,
  starred: false,
  repositories: [],
  createdBy: null,
};
const DESIGN = {
  id: "design-id",
  name: "design",
  channelType: "public" as const,
  starred: false,
  repositories: [],
  createdBy: null,
};

function renderList() {
  return render(
    <Theme>
      <ChannelsList />
    </Theme>,
  );
}

describe("ChannelsList", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.channels = [ME, ENG, DESIGN];
    mocks.unreadSessions = {};
    mocks.blockedSessions = {};
    mocks.channelsLayout = true;
    // The pane store is module state: reset to its resting value so a test that
    // slides the slider can't hand the next one a pre-focused search box.
    showChannelPane();
    // Same for the collapse state — a test that folds a group away would
    // otherwise hide its rows from every test that runs after it.
    useSidebarStore.setState({ collapsedSections: new Set() });
    useSpaceTreeStore.setState({
      expandedSpaceIds: new Set(),
      highlightedValue: undefined,
    });
    useSidebarSearchStore.setState({
      focusRequest: 0,
    });
    mocks.totals = {};
    useCurrentChannelStore.setState({ currentChannelId: null });
    mocks.tasks = [
      {
        id: "task-new",
        title: "Ship the tree",
        channel: ENG.id,
        updated_at: "2026-08-02T00:00:00Z",
      },
      {
        id: "task-old",
        title: "Write the tests",
        channel: ENG.id,
        updated_at: "2026-08-01T00:00:00Z",
      },
    ];
  });

  it("opens a space in the sidebar without navigating the main window", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByText("engineering"));

    expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
    expect(useChannelPaneStore.getState().animateTransition).toBe(true);
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it("pins personal above the channels, with its ⌘1 shortcut", () => {
    renderList();
    const me = screen.getByText("personal");
    const eng = screen.getByText("engineering");
    expect(
      me.compareDocumentPosition(eng) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // ChannelHotkeys binds ⌘1-9 to the same slots; the list is where they're
    // advertised now that the switcher popover is gone.
    expect(me.parentElement?.textContent).toMatch(/personal(⌘|Ctrl)/);
  });

  describe("group headings", () => {
    beforeEach(() => {
      mocks.channels = [ME, { ...ENG, starred: true }, DESIGN];
    });

    it("rebrands only the spaces layout", () => {
      const view = renderList();
      expect(screen.getByRole("heading", { name: "Spaces" })).toBeTruthy();

      view.unmount();
      mocks.channelsLayout = false;
      renderList();
      expect(screen.queryByRole("heading", { name: "Spaces" })).toBeNull();
      expect(screen.getByText("Channels")).toBeTruthy();
    });
  });

  describe("search", () => {
    // The list is the only way to switch channels now, so with a few dozen
    // channels it has to be filterable rather than only scrollable.
    it("narrows the list to matching channels", async () => {
      const user = userEvent.setup();
      renderList();

      await user.type(screen.getByLabelText("Search spaces"), "eng");

      expect(screen.getByText("engineering")).toBeTruthy();
      expect(screen.queryByText("design")).toBeNull();
      expect(screen.queryByText("personal")).toBeNull();
    });

    // Grouping is for browsing; once you've named what you want, "Starred" and
    // "Channels" headings only stand between you and the one row that matches.
    it("drops the group headings while filtering", async () => {
      const user = userEvent.setup();
      mocks.channels = [ME, { ...ENG, starred: true }, DESIGN];
      renderList();
      expect(screen.getByText("Starred")).toBeTruthy();

      await user.type(screen.getByLabelText("Search spaces"), "eng");

      expect(screen.queryByText("Starred")).toBeNull();
      expect(screen.getByText("engineering")).toBeTruthy();
    });

    // The alpha renders this list as a plain tree with no slider around it, and
    // ChannelHotkeys doesn't bind ⌘1-9 there either — so neither shows.
    it("is absent off the channels layout, along with the shortcut hints", () => {
      mocks.channelsLayout = false;
      renderList();
      expect(screen.queryByLabelText("Search spaces")).toBeNull();
      expect(screen.getByText("personal").parentElement?.textContent).toBe(
        "personal",
      );
    });

    it("says so when nothing matches", async () => {
      const user = userEvent.setup();
      renderList();

      await user.type(screen.getByLabelText("Search spaces"), "zzz");

      expect(screen.getByText(/No spaces match/)).toBeTruthy();
    });

    // Searching is a keyboard flow start to finish: you never leave the input
    // to reach the row you just named.
    it("opens the highlighted result on Enter", async () => {
      const user = userEvent.setup();
      renderList();

      await user.type(screen.getByLabelText("Search spaces"), "eng");
      await user.keyboard("{Enter}");

      expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
      expect(mocks.navigate).not.toHaveBeenCalled();
    });

    it("moves the highlight with the arrow keys", async () => {
      const user = userEvent.setup();
      renderList();

      // "me", "design" and "engineering" all contain an "e"; the first is
      // highlighted to begin with, so one press down lands on the second.
      await user.type(screen.getByLabelText("Search spaces"), "e");
      await user.keyboard("{ArrowDown}{Enter}");

      expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
      expect(mocks.navigate).not.toHaveBeenCalled();
    });

    // Base UI's clear button is a tabIndex=-1 decoration by default, which left
    // the keyboard with no way out of a query.
    it("clears on Escape", async () => {
      const user = userEvent.setup();
      renderList();
      const input = screen.getByLabelText("Search spaces");

      await user.type(input, "eng");
      expect(screen.queryByText("design")).toBeNull();

      await user.keyboard("{Escape}");

      expect((input as HTMLInputElement).value).toBe("");
      expect(screen.getByText("design")).toBeTruthy();
    });

    it("gives the clear button a tab stop", async () => {
      const user = userEvent.setup();
      renderList();

      await user.type(screen.getByLabelText("Search spaces"), "eng");

      const clear = screen.getByLabelText("Clear search");
      expect((clear as HTMLElement).tabIndex).toBe(0);

      await user.tab();
      expect(document.activeElement).toBe(clear);
      await user.keyboard("{Enter}");
      expect(
        (screen.getByLabelText("Search spaces") as HTMLInputElement).value,
      ).toBe("");
    });
  });

  // The list is a switcher first: arrowing to a space has to work the moment
  // the pane opens, not only once there's something to filter by.
  describe("keyboard traversal with no query", () => {
    it("walks the rows and opens the highlighted one", async () => {
      const user = userEvent.setup();
      renderList();

      await user.click(screen.getByLabelText("Search spaces"));
      // Nothing is highlighted until a key moves it, and the headings are rows
      // of their own: Starred, #me, Spaces, then the space below it.
      await user.keyboard(
        "{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}",
      );

      expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
      expect(mocks.navigate).not.toHaveBeenCalled();
    });

    // The heading is a row of the tree, so it answers the tree's keys. A
    // heading missing from the flat node list would leave the highlight index
    // and the rendered rows disagreeing from there down.
    it("folds a section from its heading and opens it again", async () => {
      const user = userEvent.setup();
      renderList();

      await user.click(screen.getByLabelText("Search spaces"));
      // Onto the Spaces heading: Starred, #me, Spaces.
      await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{ArrowLeft}");
      expect(screen.queryByText("engineering")).toBeNull();

      await user.keyboard("{ArrowRight}");
      expect(screen.getByText("engineering")).toBeTruthy();
    });

    // A kept-mounted collapsed row would still be an option, so ↓ would walk
    // onto spaces that were folded away.
    it("drops a collapsed group's rows from the list", async () => {
      const user = userEvent.setup();
      renderList();
      expect(screen.getByText("engineering")).toBeTruthy();

      await user.click(screen.getByRole("option", { name: "Spaces" }));

      expect(screen.queryByText("engineering")).toBeNull();
    });
  });

  // The list is a tree: a space opens onto its most recent tasks, and the whole
  // of it is reachable from the search box without ever leaving the keyboard.
  describe("space tree", () => {
    it("opens a space onto its recent tasks with ArrowRight", async () => {
      const user = userEvent.setup();
      renderList();

      await user.click(screen.getByLabelText("Search spaces"));
      // Nothing is highlighted to begin with: down through the Starred heading,
      // #me and the Spaces heading reaches "engineering".
      await user.keyboard(
        "{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{ArrowRight}",
      );

      expect(screen.getByText("Ship the tree")).toBeTruthy();
      expect(screen.getByText("Write the tests")).toBeTruthy();
      // Opening the tree is not opening the space.
      expect(useCurrentChannelStore.getState().currentChannelId).toBeNull();
    });

    // The fiddly half: the highlight is an index into a flat list, so walking
    // back to the parent has to happen before its children stop existing.
    it("walks into the tasks and back out to their space", async () => {
      const user = userEvent.setup();
      renderList();

      await user.click(screen.getByLabelText("Search spaces"));
      await user.keyboard(
        "{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{ArrowRight}{ArrowDown}{ArrowDown}",
      );
      // On the second task, two rows below its space.
      await user.keyboard("{ArrowLeft}");

      expect(screen.queryByText("Ship the tree")).toBeNull();
      // The highlight came back to the space it closed, so ⏎ opens that space
      // rather than whatever row inherited the index.
      await user.keyboard("{Enter}");
      expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
    });

    it("toggles from the caret without opening the space", async () => {
      const user = userEvent.setup();
      renderList();

      await user.click(screen.getByLabelText("Expand engineering"));
      expect(screen.getByText("Ship the tree")).toBeTruthy();
      expect(useCurrentChannelStore.getState().currentChannelId).toBeNull();

      await user.click(screen.getByLabelText("Collapse engineering"));
      expect(screen.queryByText("Ship the tree")).toBeNull();
    });

    it("offers Hand off… on an owned task's context menu only", async () => {
      // The API 404s a non-owner's handoff, so the menu must not offer it to one.
      mocks.tasks[0] = { ...mocks.tasks[0], authorId: 999 };
      mocks.tasks[1] = { ...mocks.tasks[1], authorId: 7 };
      const user = userEvent.setup();
      renderList();

      await user.click(screen.getByLabelText("Expand engineering"));
      fireEvent.contextMenu(screen.getByText("Ship the tree"));
      expect(
        await screen.findByRole("menuitem", { name: "Hand off…" }),
      ).toBeTruthy();
      await user.keyboard("{Escape}");

      fireEvent.contextMenu(screen.getByText("Write the tests"));
      await waitFor(() =>
        expect(
          screen.queryByRole("menuitem", { name: "Hand off…" }),
        ).toBeNull(),
      );
    });

    // Picking a session out of the tree is browsing across spaces, not a
    // request to go into one — sliding into the space would take the tree the
    // reader is working through off the screen.
    it("opens a session without leaving the list", async () => {
      const user = userEvent.setup();
      renderList();
      act(() => showChannelList());

      await user.click(screen.getByLabelText("Expand engineering"));
      await user.click(screen.getByText("Ship the tree"));

      expect(mocks.navigate).toHaveBeenCalledWith(
        expect.objectContaining({
          params: { channelId: ENG.id, taskId: "task-new" },
        }),
      );
      expect(useChannelPaneStore.getState().pane).toBe("list");
      // The other half of it: the route effect in ChannelsSidebar slides into
      // the space unless the navigation says to stay put.
      expect(shouldKeepListForRoute(ENG.id)).toBe(true);
      // Still scoped, so whatever asks for the channel pane next opens on the
      // space the session came from.
      expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
    });

    // The row after the last session: the keyboard has to know about it, or the
    // highlight index and the rendered options disagree from there down.
    it("walks onto View all and opens the space from it", async () => {
      const user = userEvent.setup();
      mocks.totals[ENG.id] = 7;
      renderList();

      await user.click(screen.getByLabelText("Search spaces"));
      await user.keyboard(
        "{ArrowDown}{ArrowDown}{ArrowDown}{ArrowDown}{ArrowRight}",
      );
      expect(screen.getByText("view all")).toBeTruthy();

      // Past both sessions and onto the row below them.
      await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");

      expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
    });

    it("says when an expanded space has nothing in it", async () => {
      const user = userEvent.setup();
      renderList();

      await user.click(screen.getByLabelText("Expand design"));

      expect(screen.getByText("No sessions yet")).toBeTruthy();
    });
  });

  // Sliding back from a space, the list is what you came here for — so it hands
  // the search box the caret rather than making you click it.
  describe("focus on returning to the list", () => {
    // ⌘⇧S is bound in ChannelHotkeys, which can only ask; the list is what
    // actually takes the keyboard.
    it("takes the keyboard on a focus request", async () => {
      const firstRender = renderList();

      act(() => requestSidebarSearchFocus());

      await waitFor(() =>
        expect(document.activeElement).toBe(
          screen.getByLabelText("Search spaces"),
        ),
      );

      firstRender.unmount();
      renderList();

      expect(document.activeElement).not.toBe(
        screen.getByLabelText("Search spaces"),
      );
    });

    it("focuses the search box when the pane slides back", async () => {
      renderList();
      expect(document.activeElement).not.toBe(
        screen.getByLabelText("Search spaces"),
      );

      act(() => showChannelList());

      await waitFor(() =>
        expect(document.activeElement).toBe(
          screen.getByLabelText("Search spaces"),
        ),
      );
    });

    // Opening a row would close an ordinary combobox, and a closed one stops
    // answering the arrow keys — the pane came back with its keyboard dead and
    // its highlight parked on the space you had just left.
    it("returns the highlight to the top with the arrows live", async () => {
      const user = userEvent.setup();
      renderList();

      await user.click(screen.getByText("engineering"));
      act(() => showChannelList());
      await waitFor(() =>
        expect(document.activeElement).toBe(
          screen.getByLabelText("Search spaces"),
        ),
      );
      mocks.navigate.mockClear();

      // From the top, three presses down is "engineering" again — the two
      // headings are rows too. Left where it was, this would have landed on the
      // row after it.
      await user.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");

      expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
      expect(mocks.navigate).not.toHaveBeenCalled();
    });

    it("selects a stale query so the next keystroke replaces it", async () => {
      const user = userEvent.setup();
      renderList();
      const input = screen.getByLabelText("Search spaces") as HTMLInputElement;

      await user.type(input, "eng");
      await user.click(screen.getByText("engineering"));
      act(() => showChannelList());

      await waitFor(() => expect(document.activeElement).toBe(input));
      expect(input.selectionStart).toBe(0);
      expect(input.selectionEnd).toBe("eng".length);
    });

    it("leaves focus alone off the channels layout", async () => {
      mocks.channelsLayout = false;
      renderList();

      act(() => showChannelList());

      await waitFor(() =>
        expect(screen.queryByLabelText("Search spaces")).toBeNull(),
      );
      expect(document.activeElement).toBe(document.body);
    });
  });
});
