import { Theme } from "@radix-ui/themes";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  featureFlags: new Map<string, boolean>(),
  channelsLayout: false,
  channelsEnabled: false,
  channels: [] as { id: string; name: string; path: string }[],
  channelsLoading: false,
  archivedTaskIds: new Set<string>(),
  navigateToArchived: vi.fn(),
  track: vi.fn(),
  routeChannelId: undefined as string | undefined,
}));

vi.mock("@posthog/ui/shell/analytics", () => ({
  track: (...args: unknown[]) => mocks.track(...args),
}));

vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: (key: string) => mocks.featureFlags.get(key) ?? true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => mocks.channelsLayout,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: mocks.channels,
    isLoading: mocks.channelsLoading,
  }),
}));
vi.mock("@posthog/ui/features/archive/useArchivedTaskIds", () => ({
  useArchivedTaskIds: () => mocks.archivedTaskIds,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelStars", () => ({
  useChannelStars: () => ({ starredRefToShortcutId: new Map() }),
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToArchived: (...args: unknown[]) => mocks.navigateToArchived(...args),
}));

// The sidebar's children each mount their own query stack; this suite is about
// the shell's own decisions, so they're stubbed out.
vi.mock("@posthog/ui/features/canvas/components/ChannelNav", () => ({
  ChannelNav: () => null,
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelSidebar", () => ({
  ChannelSidebar: ({ channelId }: { channelId: string }) => (
    <div data-testid="channel-sidebar">{channelId}</div>
  ),
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelsList", () => ({
  ChannelsList: () => <div data-testid="channels-list" />,
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelsFab", () => ({
  ChannelsFab: () => null,
}));
vi.mock("@posthog/ui/features/sidebar/components/SidebarNavSection", () => ({
  SidebarNavSection: () => <div data-testid="sidebar-nav-section" />,
}));
vi.mock("@posthog/ui/features/sidebar/components/TasksHeader", () => ({
  TasksHeader: () => <div data-testid="tasks-header" />,
}));
vi.mock("@posthog/ui/features/sidebar/components/SidebarMenu", () => ({
  SidebarMenu: () => <div data-testid="sidebar-menu" />,
}));
vi.mock("@posthog/ui/features/sidebar/components/ProjectSwitcher", () => ({
  ProjectSwitcher: () => null,
}));
vi.mock("@posthog/ui/features/sidebar/components/UpdateBanner", () => ({
  UpdateBanner: () => null,
}));
vi.mock("@posthog/ui/features/loops/components/LoopsPromoCard", () => ({
  LoopsPromoCard: () => null,
}));
vi.mock("@posthog/ui/features/workspace/useWorkspace", () => ({
  useWorkspaces: () => ({ data: {}, isFetched: true }),
}));
vi.mock("@tanstack/react-router", () => ({
  useParams: () => ({ channelId: mocks.routeChannelId }),
}));

import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  showChannelList,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { ChannelsSidebar } from "./ChannelsSidebar";

function renderSidebar() {
  return render(
    <Theme>
      <ChannelsSidebar />
    </Theme>,
  );
}

const ME = { id: "me-id", name: "me", path: "/me" };

describe("ChannelsSidebar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.featureFlags.clear();
    mocks.channelsLayout = false;
    mocks.channels = [];
    mocks.channelsLoading = false;
    mocks.archivedTaskIds = new Set();
    mocks.track.mockClear();
    mocks.routeChannelId = undefined;
    useCurrentChannelStore.setState({ currentChannelId: null });
    useChannelPaneStore.setState({ pane: "channel" });
    useSidebarStore.setState({ channelsEnabled: false, open: true });
  });

  // The sidebar is a two-pane slider: the channel list, and the channel you're
  // in. Both stay mounted, so "which one is showing" is the offscreen pane
  // being inert rather than unmounted.
  describe("the channel-list slider", () => {
    const ENG = { id: "eng-id", name: "eng", path: "/eng" };
    const listIsInteractive = () =>
      !screen.getByTestId("channels-list").parentElement?.hasAttribute("inert");

    beforeEach(() => {
      mocks.channelsLayout = true;
      mocks.channels = [ME, ENG];
    });

    it("rests on the channel you're in", () => {
      mocks.routeChannelId = ENG.id;
      renderSidebar();
      expect(screen.getByTestId("channel-sidebar").textContent).toBe(ENG.id);
      expect(listIsInteractive()).toBe(false);
    });

    // Browsing the list is a sidebar move, not a navigation: the channel stays
    // scoped, so the main pane keeps showing what it was showing.
    it("shows the list on the way back, without leaving the channel", () => {
      mocks.routeChannelId = ENG.id;
      renderSidebar();

      act(() => showChannelList());

      expect(listIsInteractive()).toBe(true);
      expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);
    });

    // Opening a channel from anywhere — a deep link, a mention, ⌘1-9 — has to
    // land on the channel even if the list was left open.
    it("follows the route back into a channel", () => {
      mocks.routeChannelId = ENG.id;
      const { rerender } = renderSidebar();
      act(() => showChannelList());

      mocks.routeChannelId = ME.id;
      rerender(
        <Theme>
          <ChannelsSidebar />
        </Theme>,
      );

      expect(listIsInteractive()).toBe(false);
      expect(screen.getByTestId("channel-sidebar").textContent).toBe(ME.id);
    });

    it("stays on the list while no channel resolves", () => {
      mocks.channels = [ENG];
      renderSidebar();
      expect(listIsInteractive()).toBe(true);
      expect(screen.queryByTestId("channel-sidebar")).toBeNull();
    });

    // A trackpad swipe reaches the panes as a horizontal wheel. Right (negative
    // deltaX, the platform "back" direction) leaves the channel; left returns to
    // the one still scoped.
    describe("swiping", () => {
      // Wheel deltas within one gesture arrive back to back; a pause between
      // them is what ends it. Fake timers let a test say which it's sending.
      const wheel = (deltaX: number, deltaY = 0) =>
        act(() => {
          screen.getByTestId("channels-list").dispatchEvent(
            new WheelEvent("wheel", {
              deltaX,
              deltaY,
              bubbles: true,
              cancelable: true,
            }),
          );
        });
      const pause = () => act(() => void vi.advanceTimersByTime(500));

      beforeEach(() => {
        vi.useFakeTimers();
        mocks.routeChannelId = ENG.id;
      });
      afterEach(() => vi.useRealTimers());

      it("goes back to the list and forward into the channel", () => {
        renderSidebar();

        wheel(-80);
        expect(listIsInteractive()).toBe(true);
        // The channel is browsed away from, not left.
        expect(useCurrentChannelStore.getState().currentChannelId).toBe(ENG.id);

        pause();
        wheel(80);
        expect(listIsInteractive()).toBe(false);
      });

      // One flick is dozens of small deltas, so the distance has to add up
      // across them rather than be read off any one event.
      it("adds a gesture's deltas up", () => {
        renderSidebar();
        wheel(-20);
        expect(listIsInteractive()).toBe(false);
        wheel(-20);
        wheel(-20);
        expect(listIsInteractive()).toBe(true);
      });

      it("ignores a mostly-vertical wheel", () => {
        renderSidebar();
        wheel(-80, -200);
        expect(listIsInteractive()).toBe(false);
      });

      it("forgets a nudge once the gesture ends", () => {
        renderSidebar();
        wheel(-30);
        pause();
        wheel(-30);
        expect(listIsInteractive()).toBe(false);
      });

      // The momentum tail of one flick keeps delivering deltas; read as fresh
      // travel they'd swipe straight back to where the flick started.
      it("does not let one flick's momentum swipe twice", () => {
        renderSidebar();
        wheel(-80);
        wheel(200);
        expect(listIsInteractive()).toBe(true);
      });
    });
  });

  describe("the Archived row", () => {
    beforeEach(() => {
      mocks.archivedTaskIds = new Set(["archived-1"]);
    });

    // The layout puts an Archive action on every item row, so the destination
    // still has to exist — it moved into the account menu (ProjectSwitcher),
    // which is where navigateToArchived is called from now.
    it("leaves the sidebar body under the channels layout", () => {
      mocks.channelsLayout = true;
      mocks.channels = [ME];
      renderSidebar();
      expect(screen.queryByText("Archived")).toBeNull();
    });

    it("is present with neither channels world on", () => {
      renderSidebar();
      expect(screen.getByText("Archived")).toBeTruthy();
    });

    // The alpha replaced the task list with the channel tree, so the row went
    // with it — that part is deliberate.
    it("is absent in the channels alpha", () => {
      useSidebarStore.setState({ channelsEnabled: true });
      mocks.featureFlags.set(PROJECT_BLUEBIRD_FLAG, true);
      renderSidebar();
      expect(screen.queryByText("Archived")).toBeNull();
    });

    it("stays hidden when nothing is archived", () => {
      mocks.channelsLayout = true;
      mocks.archivedTaskIds = new Set();
      renderSidebar();
      expect(screen.queryByText("Archived")).toBeNull();
    });
  });

  describe("auto-scoping to #me", () => {
    it("keeps a deep-linked channel instead of overwriting it with #me", () => {
      mocks.channelsLayout = true;
      mocks.channels = [ME, { id: "eng-id", name: "eng", path: "/eng" }];
      mocks.routeChannelId = "eng-id";

      renderSidebar();

      expect(useCurrentChannelStore.getState().currentChannelId).toBe("eng-id");
    });

    it("scopes to the personal channel once the list lands", () => {
      mocks.channelsLayout = true;
      mocks.channels = [ME];
      renderSidebar();
      expect(useCurrentChannelStore.getState().currentChannelId).toBe("me-id");
    });

    // Both flags behind the layout re-evaluate on every flags payload, so a
    // momentary false must not permanently strand the sidebar unscoped: the
    // auto-scope latch has to reset when the layout turns off.
    it("re-scopes after the layout flag flickers off and back on", () => {
      mocks.channelsLayout = true;
      mocks.channels = [ME];
      const { rerender } = renderSidebar();
      expect(useCurrentChannelStore.getState().currentChannelId).toBe("me-id");

      mocks.channelsLayout = false;
      rerender(
        <Theme>
          <ChannelsSidebar />
        </Theme>,
      );
      expect(useCurrentChannelStore.getState().currentChannelId).toBeNull();

      mocks.channelsLayout = true;
      rerender(
        <Theme>
          <ChannelsSidebar />
        </Theme>,
      );
      expect(useCurrentChannelStore.getState().currentChannelId).toBe("me-id");
    });

    it("does not scope to a channel the project does not have", () => {
      mocks.channelsLayout = true;
      mocks.channels = [{ id: "eng", name: "eng", path: "/eng" }];
      renderSidebar();
      expect(useCurrentChannelStore.getState().currentChannelId).toBeNull();
      expect(screen.queryByTestId("channel-sidebar")).toBeNull();
    });

    // A stale id from a previous project must not be rendered as a channel.
    it("clears a scoped channel missing from the loaded list", () => {
      mocks.channelsLayout = true;
      mocks.channels = [ME];
      useCurrentChannelStore.setState({ currentChannelId: "from-old-project" });
      renderSidebar();
      expect(useCurrentChannelStore.getState().currentChannelId).not.toBe(
        "from-old-project",
      );
    });
  });

  it("renders the flag-off sidebar menu untouched", () => {
    renderSidebar();
    expect(screen.getByTestId("sidebar-menu")).toBeTruthy();
    expect(screen.getByTestId("sidebar-nav-section")).toBeTruthy();
  });

  describe("space-viewed tracking", () => {
    // The event used to fire from ChannelsList, which the new layout barely
    // renders — so space adoption would have read as zero once the flag landed.
    it("fires from the shell under the channels layout", () => {
      mocks.channelsLayout = true;
      mocks.channels = [ME, { id: "eng", name: "eng", path: "/eng" }];
      renderSidebar();
      expect(mocks.track).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.CHANNELS_SPACE_VIEWED,
        { channel_count: 1, starred_count: 0, layout: "channels" },
      );
    });

    it("does not fire outside the channels world", () => {
      mocks.channels = [ME];
      renderSidebar();
      expect(mocks.track).not.toHaveBeenCalledWith(
        ANALYTICS_EVENTS.CHANNELS_SPACE_VIEWED,
        expect.anything(),
      );
    });

    it("fires again after leaving and re-entering the channels world", () => {
      mocks.channelsLayout = true;
      mocks.channels = [ME];
      const { rerender } = renderSidebar();

      mocks.channelsLayout = false;
      rerender(
        <Theme>
          <ChannelsSidebar />
        </Theme>,
      );
      mocks.channelsLayout = true;
      rerender(
        <Theme>
          <ChannelsSidebar />
        </Theme>,
      );

      expect(mocks.track).toHaveBeenCalledTimes(2);
    });
  });
});
