import { Theme } from "@radix-ui/themes";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  channels: [] as { id: string; name: string; path: string }[],
  starredPaths: [] as string[],
  channelsLayout: true,
  navigate: vi.fn(),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => mocks.channelsLayout,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: mocks.channels, isLoading: false }),
  useChannelMutations: () => ({ createChannel: vi.fn(), isDeleting: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelStars", () => ({
  useChannelStars: () => ({
    starredRefToShortcutId: new Map(mocks.starredPaths.map((p) => [p, p])),
  }),
  useChannelStarToggle: () => ({
    isStarred: false,
    toggleStar: vi.fn(),
    removeStar: vi.fn(),
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useCreateAndOpenDashboard: () => vi.fn(),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useUnreadChannels", () => ({
  useIsChannelUnread: () => () => false,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannels", async () => {
  const actual = await vi.importActual<
    typeof import("@posthog/ui/features/canvas/hooks/useTaskChannels")
  >("@posthog/ui/features/canvas/hooks/useTaskChannels");
  return { ...actual, useTaskChannels: () => ({ channels: [] }) };
});
vi.mock("@posthog/ui/features/canvas/components/RenameChannelModal", () => ({
  RenameChannelModal: () => null,
}));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => mocks.navigate,
  useRouterState: () => "/website",
}));

import {
  showChannelList,
  showChannelPane,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { ChannelsList } from "./ChannelsList";

const ME = { id: "me-id", name: "me", path: "/me" };
const ENG = { id: "eng-id", name: "engineering", path: "/engineering" };
const DESIGN = { id: "design-id", name: "design", path: "/design" };

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
    mocks.starredPaths = [];
    mocks.channelsLayout = true;
    // The pane store is module state: reset to its resting value so a test that
    // slides the slider can't hand the next one a pre-focused search box.
    showChannelPane();
    // Same for the collapse state — a test that folds a group away would
    // otherwise hide its rows from every test that runs after it.
    useSidebarStore.setState({ collapsedSections: new Set() });
  });

  it("opens a space in the sidebar without navigating the main window", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByText("engineering"));

    expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it("pins #me above the channels, with its ⌘1 shortcut", () => {
    renderList();
    const me = screen.getByText("me");
    const eng = screen.getByText("engineering");
    expect(
      me.compareDocumentPosition(eng) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // ChannelHotkeys binds ⌘1-9 to the same slots; the list is where they're
    // advertised now that the switcher popover is gone.
    expect(me.parentElement?.textContent).toMatch(/me(⌘|Ctrl)/);
  });

  // "Starred" and "Spaces" are headings over the rows. Spaces receive a small
  // Slack-style inset; the alpha keeps its deeper tree indentation.
  describe("group headings", () => {
    beforeEach(() => {
      mocks.starredPaths = [ENG.path];
    });

    it("slightly indents rows under the layout", () => {
      renderList();
      expect(screen.getByText("engineering").closest("button")).toHaveClass(
        "pl-4",
      );
      expect(screen.getByText("me").closest("button")).not.toHaveClass("pl-4");
    });

    it("keeps the indented tree off the layout", () => {
      mocks.channelsLayout = false;
      renderList();
      expect(screen.getByText("engineering").closest(".pl-5")).toBeTruthy();
      expect(screen.getByText("engineering").closest("button")).not.toHaveClass(
        "pl-4",
      );
    });

    it("rebrands only the spaces layout", () => {
      renderList();
      expect(screen.getByText("Spaces")).toBeTruthy();

      mocks.channelsLayout = false;
      renderList();
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
      expect(screen.queryByText("me")).toBeNull();
    });

    // Grouping is for browsing; once you've named what you want, "Starred" and
    // "Channels" headings only stand between you and the one row that matches.
    it("drops the group headings while filtering", async () => {
      const user = userEvent.setup();
      mocks.starredPaths = [ENG.path];
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
      expect(screen.getByText("me").parentElement?.textContent).toBe("me");
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
      await user.keyboard("{ArrowDown}{Enter}");

      expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
      expect(mocks.navigate).not.toHaveBeenCalled();
    });

    // Base UI resets the highlight when the pointer leaves a row, and
    // `autoHighlight="always"` then snaps it back to the top — so drifting the
    // mouse across the gap between two rows threw the keyboard back to #me.
    it("keeps the highlight when the pointer leaves a row", async () => {
      const user = userEvent.setup();
      renderList();

      await user.click(screen.getByLabelText("Search spaces"));
      const row = screen.getByText("engineering");
      await user.hover(row);
      await user.unhover(row);
      await user.keyboard("{Enter}");

      expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
      expect(mocks.navigate).not.toHaveBeenCalled();
    });

    // A kept-mounted collapsed row would still be an option, so ↓ would walk
    // onto spaces that were folded away.
    it("drops a collapsed group's rows from the list", async () => {
      const user = userEvent.setup();
      renderList();
      expect(screen.getByText("engineering")).toBeTruthy();

      await user.click(screen.getByText("Spaces"));

      expect(screen.queryByText("engineering")).toBeNull();
    });
  });

  // Sliding back from a space, the list is what you came here for — so it hands
  // the search box the caret rather than making you click it.
  describe("focus on returning to the list", () => {
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

      // From the top, one press down is "engineering" again. Left where it was,
      // it would have been the row after it.
      await user.keyboard("{ArrowDown}{Enter}");

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
