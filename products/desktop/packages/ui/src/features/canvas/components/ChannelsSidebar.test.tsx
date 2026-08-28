import { browserTabsStore } from "@posthog/core/browser-tabs/browserTabsStore";
import { Theme } from "@radix-ui/themes";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  featureFlags: new Map<string, boolean>(),
  channelsLayout: false,
  channelsEnabled: false,
  channels: [] as {
    id: string;
    name: string;
    channelType: "public" | "personal";
    starred: boolean;
  }[],
  channelsLoading: false,
  archivedTaskIds: new Set<string>(),
  navigateToArchived: vi.fn(),
  track: vi.fn(),
  routeChannelId: undefined as string | undefined,
  fullPath: "/spaces/$channelId",
  markChannelSeen: vi.fn(),
  historyTabId: undefined as string | undefined,
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
vi.mock("@posthog/ui/features/canvas/hooks/useMarkChannelSeen", () => ({
  useMarkChannelSeen: (channelId: string | undefined) =>
    mocks.markChannelSeen(channelId),
}));
vi.mock("@posthog/ui/features/archive/useArchivedTaskIds", () => ({
  useArchivedTaskIds: () => mocks.archivedTaskIds,
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToArchived: (...args: unknown[]) => mocks.navigateToArchived(...args),
}));

// The sidebar's children each mount their own query stack; this suite is about
// the shell's own decisions, so they're stubbed out.
vi.mock("@posthog/ui/features/canvas/components/ActivityFeedList", () => ({
  ActivityFeedList: () => <div data-testid="activity-feed" />,
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
vi.mock("@posthog/ui/features/workspace/useWorkspace", () => ({
  useWorkspaces: () => ({ data: {}, isFetched: true }),
}));
vi.mock("@tanstack/react-router", () => ({
  useParams: () => ({ channelId: mocks.routeChannelId }),
  useRouterState: ({
    select,
  }: {
    select: (s: {
      matches: { fullPath: string }[];
      location: { state: { tabId?: string } };
    }) => unknown;
  }) =>
    select({
      matches: [{ fullPath: mocks.fullPath }],
      location: { state: { tabId: mocks.historyTabId } },
    }),
}));

import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  showChannelList,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { ChannelRouteSync } from "./ChannelRouteSync";
import { ChannelsSidebar } from "./ChannelsSidebar";

// The same pair the shell mounts: the column's contents follow the scoped space.
function renderSidebar() {
  return render(
    <Theme>
      <ChannelRouteSync />
      <ChannelsSidebar />
    </Theme>,
  );
}

const ME = {
  id: "me-id",
  name: "me",
  channelType: "personal" as const,
  starred: false,
};
const ENG = {
  id: "eng-id",
  name: "eng",
  channelType: "public" as const,
  starred: false,
};

function setPendingTabSwitch({
  href,
  viewState,
  channelId,
}: {
  href: string;
  viewState: { listOpen: boolean; spaceId: string | null };
  channelId: string | null;
}): void {
  mocks.historyTabId = "target-tab";
  browserTabsStore.getState().setSnapshot({
    windows: [
      {
        id: "window-1",
        isPrimary: true,
        bounds: null,
        activeTabId: "channel-tab",
      },
    ],
    tabs: [
      {
        id: "channel-tab",
        windowId: "window-1",
        href: `/spaces/${ENG.id}`,
        viewState: { listOpen: false, spaceId: ENG.id },
        dashboardId: null,
        taskId: null,
        channelId: ENG.id,
        channelSection: null,
        appView: null,
        position: 1_000,
        scrollState: null,
        createdAt: 1,
        lastActiveAt: 1,
      },
      {
        id: "target-tab",
        windowId: "window-1",
        href,
        viewState,
        dashboardId: null,
        taskId: null,
        channelId,
        channelSection: null,
        appView: null,
        position: 2_000,
        scrollState: null,
        createdAt: 2,
        lastActiveAt: 2,
      },
    ],
  });
}

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
    mocks.fullPath = "/spaces/$channelId/";
    mocks.historyTabId = undefined;
    browserTabsStore.getState().setSnapshot({ windows: [], tabs: [] });
    useCurrentChannelStore.setState({ currentChannelId: null });
    useChannelPaneStore.setState({
      pane: "channel",
      animateTransition: false,
    });
    // hasUserSetOpen pins `open`, so the auto-open effect (which sees no
    // workspaces in this harness) can't collapse it out from under the tests.
    useSidebarStore.setState({
      channelsEnabled: false,
      open: true,
      hasUserSetOpen: true,
    });
  });

  // The sidebar is a two-pane slider: the channel list, and the channel you're
  // in. Both stay mounted, so "which one is showing" is the offscreen pane
  // being inert rather than unmounted.
  describe("the channel-list slider", () => {
    const listIsInteractive = () =>
      !screen.getByTestId("channels-list").parentElement?.hasAttribute("inert");

    beforeEach(() => {
      mocks.channelsLayout = true;
      mocks.channels = [ME, ENG];
    });

    // Activity owns this column whenever its route does, so the space tree can
    // never be what a reader finds under the Activity destination.
    it("hands the column to the activity feed on the Activity route", () => {
      mocks.routeChannelId = undefined;
      mocks.fullPath = "/activity";
      renderSidebar();

      expect(screen.getByTestId("activity-feed")).toBeInTheDocument();
      expect(screen.queryByTestId("channels-list")).not.toBeInTheDocument();
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

    it("shows an in-flight tab's list before its route settles", () => {
      mocks.routeChannelId = ENG.id;
      setPendingTabSwitch({
        href: "/spaces",
        viewState: { listOpen: true, spaceId: ENG.id },
        channelId: null,
      });

      renderSidebar();

      expect(listIsInteractive()).toBe(true);
      expect(useChannelPaneStore.getState().pane).toBe("channel");
    });

    it("does not mark an in-flight tab's channel seen", () => {
      mocks.routeChannelId = ENG.id;
      setPendingTabSwitch({
        href: `/spaces/${ME.id}`,
        viewState: { listOpen: false, spaceId: ME.id },
        channelId: ME.id,
      });

      renderSidebar();

      expect(screen.getByTestId("channel-sidebar").textContent).toBe(ME.id);
      expect(mocks.markChannelSeen).toHaveBeenLastCalledWith(undefined);
    });

    it("marks a channel seen only while its pane is visible", () => {
      mocks.routeChannelId = ENG.id;
      renderSidebar();
      expect(mocks.markChannelSeen).toHaveBeenLastCalledWith(ENG.id);

      act(() => showChannelList());

      expect(mocks.markChannelSeen).toHaveBeenLastCalledWith(undefined);
    });

    // ⌘B collapses the sidebar to zero width but keeps the pane mounted. A poll
    // landing behind it must not stamp the channel seen — nobody saw the pane.
    it("does not mark a channel seen while the sidebar is closed", () => {
      mocks.routeChannelId = ENG.id;
      useSidebarStore.setState({ open: false });
      renderSidebar();
      expect(mocks.markChannelSeen).toHaveBeenLastCalledWith(undefined);
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
          <ChannelRouteSync />
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

    // A deep link back to the channel is a request to see it, so a latch armed
    // before an intervening channel-less route must not strand it on the list.
    it("does not hold the list for a deep link after a channel-less route", () => {
      mocks.routeChannelId = ENG.id;
      const { rerender } = renderSidebar();
      act(() => {
        showChannelList({ keepForRoute: ENG.id });
      });
      expect(listIsInteractive()).toBe(true);

      mocks.routeChannelId = undefined;
      rerender(
        <Theme>
          <ChannelRouteSync />
          <ChannelsSidebar />
        </Theme>,
      );

      mocks.routeChannelId = ENG.id;
      rerender(
        <Theme>
          <ChannelRouteSync />
          <ChannelsSidebar />
        </Theme>,
      );

      expect(listIsInteractive()).toBe(false);
      expect(screen.getByTestId("channel-sidebar").textContent).toBe(ENG.id);
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
      mocks.channels = [ME, ENG];
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
          <ChannelRouteSync />
          <ChannelsSidebar />
        </Theme>,
      );
      expect(useCurrentChannelStore.getState().currentChannelId).toBeNull();

      mocks.channelsLayout = true;
      rerender(
        <Theme>
          <ChannelRouteSync />
          <ChannelsSidebar />
        </Theme>,
      );
      expect(useCurrentChannelStore.getState().currentChannelId).toBe("me-id");
    });

    it("does not scope to a channel the project does not have", () => {
      mocks.channelsLayout = true;
      mocks.channels = [ENG];
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
      mocks.channels = [ME, ENG];
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
          <ChannelRouteSync />
          <ChannelsSidebar />
        </Theme>,
      );
      mocks.channelsLayout = true;
      rerender(
        <Theme>
          <ChannelRouteSync />
          <ChannelsSidebar />
        </Theme>,
      );

      expect(mocks.track).toHaveBeenCalledTimes(2);
    });
  });
});
