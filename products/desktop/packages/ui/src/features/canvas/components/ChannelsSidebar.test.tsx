import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  featureFlags: new Map<string, boolean>(),
  channelsLayout: false,
  channelsEnabled: false,
  channels: [] as { id: string; name: string; path: string }[],
  channelsLoading: false,
  archivedTaskIds: new Set<string>(),
  navigateToArchived: vi.fn(),
  track: vi.fn(),
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
vi.mock("@posthog/ui/features/canvas/components/SpacesSidebarNav", () => ({
  SpacesSidebarNav: () => <div data-testid="spaces-sidebar-nav" />,
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

import { PROJECT_BLUEBIRD_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
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
    useSidebarStore.setState({ channelsEnabled: false, open: true });
  });

  describe("the static spaces nav", () => {
    // Under `code-spaces-layout` the slider is gone: the shell renders the
    // static nav where every space expands with its tasks beneath it.
    it("renders the static spaces nav instead of the panes", () => {
      mocks.channelsLayout = true;
      mocks.channels = [ME];
      renderSidebar();
      expect(screen.getByTestId("spaces-sidebar-nav")).toBeTruthy();
      expect(screen.queryByTestId("channels-list")).toBeNull();
    });

    it("fires space-viewed tracking from the shell", () => {
      mocks.channelsLayout = true;
      mocks.channels = [ME, { id: "eng-id", name: "eng", path: "/eng" }];
      renderSidebar();
      expect(mocks.track).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.CHANNELS_SPACE_VIEWED,
        { channel_count: 1, starred_count: 0, layout: "channels" },
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

      expect(
        mocks.track.mock.calls.filter(
          ([event]) => event === ANALYTICS_EVENTS.CHANNELS_SPACE_VIEWED,
        ),
      ).toHaveLength(2);
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

  it("renders the flag-off sidebar menu untouched", () => {
    renderSidebar();
    expect(screen.getByTestId("sidebar-menu")).toBeTruthy();
    expect(screen.getByTestId("sidebar-nav-section")).toBeTruthy();
  });

  it("does not fire tracking outside the channels world", () => {
    mocks.channels = [ME];
    renderSidebar();
    expect(mocks.track).not.toHaveBeenCalledWith(
      ANALYTICS_EVENTS.CHANNELS_SPACE_VIEWED,
      expect.anything(),
    );
  });
});
