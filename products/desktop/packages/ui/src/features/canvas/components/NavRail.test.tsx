import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  featureFlags: new Map<string, boolean>(),
  fullPath: "/",
  /** The settled location, so a pick can tell "where I was" from "where I am". */
  href: "/",
  navigate: vi.fn(),
  navigateToActivity: vi.fn(),
  navigateToSpaces: vi.fn(),
  navigateToChannel: vi.fn(),
  navigateToHome: vi.fn(),
  navigateToInbox: vi.fn(),
  openSettings: vi.fn(),
  openBrowserTab: vi.fn(),
}));

vi.mock("@tanstack/react-router", () => ({
  useRouterState: ({
    select,
  }: {
    select: (s: { matches: { fullPath: string }[] }) => unknown;
  }) => select({ matches: [{ fullPath: mocks.fullPath }] }),
}));
vi.mock("@posthog/ui/router/routerRef", () => ({
  getRouterOrNull: () => ({
    navigate: mocks.navigate,
    state: { resolvedLocation: { href: mocks.href } },
  }),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useTaskActivity", () => ({
  useTaskActivity: () => ({ unreadCount: 1 }),
}));
vi.mock(
  "@posthog/ui/features/command-center/useCommandCenterActiveCount",
  () => ({ useCommandCenterActiveCount: () => 0 }),
);
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: (key: string) => mocks.featureFlags.get(key) ?? false,
}));
vi.mock("@posthog/ui/features/feature-flags/useSpacesTabs", () => ({
  useSpacesTabs: () => true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxAllReports", () => ({
  useInboxAllReports: () => ({ counts: { pulls: 1 } }),
}));
vi.mock("@posthog/ui/features/sidebar/components/ProjectSwitcher", () => ({
  ProjectSwitcher: () => (
    <button type="button" aria-label="Project switcher">
      Project switcher
    </button>
  ),
}));
vi.mock("@posthog/ui/features/browser-tabs/useOpenBrowserTab", () => ({
  useOpenBrowserTab: () => mocks.openBrowserTab,
}));
vi.mock("@posthog/ui/features/settings/hooks/useOpenSettings", () => ({
  openSettings: mocks.openSettings,
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  getCurrentMatches: () => [{ fullPath: mocks.fullPath }],
  navigateToActivity: (...a: unknown[]) => mocks.navigateToActivity(...a),
  navigateToSpaces: (...a: unknown[]) => mocks.navigateToSpaces(...a),
  navigateToChannel: (...a: unknown[]) => mocks.navigateToChannel(...a),
  navigateToHome: (...a: unknown[]) => mocks.navigateToHome(...a),
  navigateToInbox: (...a: unknown[]) => mocks.navigateToInbox(...a),
  navigateToLoops: vi.fn(),
  navigateToCommandCenter: vi.fn(),
  navigateToSpacesContext: vi.fn(),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/canvas/components/ActivityHoverCard", () => ({
  ActivityHoverCard: () => <div>Recent activity card</div>,
}));

import { browserTabsStore } from "@posthog/core/browser-tabs/browserTabsStore";
import { DESKTOP_HOME_FLAG, type RailVisit } from "@posthog/shared";
import {
  clearKeepListForRoute,
  shouldKeepListForRoute,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { NavRail } from "./NavRail";

it("stays above floating sidebar layers", () => {
  render(<NavRail />);

  expect(screen.getByTestId("nav-rail")).toHaveClass("z-[60]");
});

/**
 * Seed where each destination was, as the ACTIVE TAB remembers it. Rail memory
 * lives on the tab rather than the window, so a pick in one tab can never
 * restore an href another tab established.
 */
function rememberVisits(lastByPane: Record<string, RailVisit>): void {
  browserTabsStore.getState().setSnapshot({
    windows: [{ id: "w1", isPrimary: true, bounds: null, activeTabId: "t1" }],
    tabs: [
      {
        id: "t1",
        windowId: "w1",
        href: null,
        viewState: { lastByPane },
        dashboardId: null,
        taskId: null,
        channelId: null,
        channelSection: null,
        appView: null,
        position: 1000,
        scrollState: null,
        createdAt: 0,
        lastActiveAt: 0,
      },
    ],
  });
}

describe("NavRail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.featureFlags.clear();
    mocks.featureFlags.set(DESKTOP_HOME_FLAG, true);
    mocks.fullPath = "/";
    mocks.href = "/";
    useSidebarStore.setState({ navItemOverrides: {}, navItemOrder: [] });
    useCurrentChannelStore.setState({ currentChannelId: null });
    useChannelPaneStore.setState({ pane: "channel" });
    rememberVisits({});
    clearKeepListForRoute();
  });

  it("hides Home when its feature flag is off", () => {
    mocks.featureFlags.set(DESKTOP_HOME_FLAG, false);

    render(<NavRail />);

    expect(screen.queryByLabelText("Home")).not.toBeInTheDocument();
  });

  it("keeps Search directly above Settings at the bottom of the rail", () => {
    render(<NavRail />);

    const buttonLabels = screen
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label"));

    expect(buttonLabels.slice(-3)).toEqual([
      "Search",
      "Settings",
      "Project switcher",
    ]);
  });

  it("puts numberless notification dots on the Activity and Self-driving buttons", () => {
    render(<NavRail />);

    for (const label of ["Activity", "Self-driving"]) {
      const button = screen.getByLabelText(label);
      const dot = button.querySelector('[data-slot="dot"]');

      expect(dot).toHaveClass("absolute", "top-0", "right-0");
      expect(dot).toHaveTextContent("");
    }
  });

  // The route is the whole answer, so a destination can never be lit over a
  // screen that isn't it.
  it.each([
    ["/", "Home"],
    ["/activity", "Activity"],
    ["/inbox/pulls/$reportId", "Self-driving"],
    ["/command-center", "Command Center"],
    ["/spaces", "Spaces"],
    ["/spaces/$channelId/loops", "Spaces"],
    ["/spaces/$channelId/context", "Spaces"],
    ["/spaces/$channelId/tasks/$taskId", "Spaces"],
  ])("lights %s as %s", (fullPath, label) => {
    mocks.fullPath = fullPath;
    render(<NavRail />);

    expect(screen.getByLabelText(label)).toHaveAttribute(
      "data-selected",
      "true",
    );
  });

  describe("with nothing remembered", () => {
    it("opens a destination in a new tab on Cmd-click", () => {
      render(<NavRail />);

      fireEvent.click(screen.getByLabelText("Self-driving"), { metaKey: true });

      expect(mocks.openBrowserTab).toHaveBeenCalledWith("/inbox");
      expect(mocks.navigateToInbox).not.toHaveBeenCalled();
      expect(mocks.navigate).not.toHaveBeenCalled();
    });

    it("keeps Settings in the current window on Cmd-click", () => {
      render(<NavRail />);

      fireEvent.click(screen.getByLabelText("Settings"), { metaKey: true });

      expect(mocks.openSettings).toHaveBeenCalledOnce();
      expect(mocks.openBrowserTab).not.toHaveBeenCalled();
    });

    it("routes to Activity from a screen that has no column for it", async () => {
      const user = userEvent.setup();
      mocks.fullPath = "/inbox";
      render(<NavRail />);

      await user.click(screen.getByLabelText("Activity"));

      expect(mocks.navigateToActivity).toHaveBeenCalledOnce();
    });

    it("leaves a whole-screen destination for the space it was scoped to", async () => {
      const user = userEvent.setup();
      useCurrentChannelStore.setState({ currentChannelId: "chan-1" });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Spaces"));

      expect(mocks.navigateToChannel).toHaveBeenCalledWith("chan-1");
      // Arriving at the space would otherwise slide straight past the list the
      // pick asked for.
      expect(shouldKeepListForRoute("chan-1")).toBe(true);
      expect(useChannelPaneStore.getState().pane).toBe("list");
    });

    it("falls back to the space index when nothing is scoped", async () => {
      const user = userEvent.setup();
      render(<NavRail />);

      await user.click(screen.getByLabelText("Spaces"));

      expect(mocks.navigateToSpaces).toHaveBeenCalledOnce();
      expect(mocks.navigateToChannel).not.toHaveBeenCalled();
    });
  });

  describe("returning to where you were", () => {
    it("reopens the page the destination was left on", async () => {
      const user = userEvent.setup();
      rememberVisits({
        spaces: {
          href: "/spaces/chan-1/loops",
          listOpen: false,
          spaceId: "chan-1",
        },
      });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Spaces"));

      expect(mocks.navigate).toHaveBeenCalledWith({
        href: "/spaces/chan-1/loops",
      });
      // Not the destination's index, which is where a pick used to land.
      expect(mocks.navigateToChannel).not.toHaveBeenCalled();
      expect(mocks.navigateToSpaces).not.toHaveBeenCalled();
    });

    // The sidebar pane is view state, so the href alone cannot bring it back.
    it("puts the space list back if that is what was on screen", async () => {
      const user = userEvent.setup();
      rememberVisits({
        spaces: {
          href: "/spaces/chan-1/tasks/task-1",
          listOpen: true,
          spaceId: "chan-1",
        },
      });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Spaces"));

      expect(useChannelPaneStore.getState().pane).toBe("list");
      expect(shouldKeepListForRoute("chan-1")).toBe(true);
    });

    // The space index and an unfiled task are both Spaces routes with no space
    // in them; the list was open over one of them and stays open.
    it("keeps the list open for a visit with no space in it", async () => {
      const user = userEvent.setup();
      mocks.fullPath = "/inbox";
      useChannelPaneStore.setState({ pane: "channel" });
      rememberVisits({
        spaces: { href: "/spaces", listOpen: true },
      });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Spaces"));

      expect(useChannelPaneStore.getState().pane).toBe("list");
    });

    it("returns to the space pane when the list was not open", async () => {
      const user = userEvent.setup();
      useChannelPaneStore.setState({ pane: "list" });
      rememberVisits({
        spaces: {
          href: "/spaces/chan-1",
          listOpen: false,
          spaceId: "chan-1",
        },
      });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Spaces"));

      expect(useChannelPaneStore.getState().pane).toBe("channel");
    });

    // A memory equal to the current page restores nothing, so the click would
    // look dead and there would be no way off the page by rail.
    it("goes to the root when the memory is the page we are on", async () => {
      const user = userEvent.setup();
      mocks.fullPath = "/activity";
      mocks.href = "/activity";
      rememberVisits({ home: { href: "/activity" } });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Home"));

      expect(mocks.navigateToHome).toHaveBeenCalledOnce();
      expect(mocks.navigate).not.toHaveBeenCalled();
    });

    it("remembers each destination separately", async () => {
      const user = userEvent.setup();
      mocks.fullPath = "/";
      rememberVisits({
        inbox: { href: "/inbox/pulls/42" },
        loops: { href: "/loops/abc" },
      });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Self-driving"));

      expect(mocks.navigate).toHaveBeenCalledWith({ href: "/inbox/pulls/42" });
      expect(mocks.navigateToInbox).not.toHaveBeenCalled();
    });
  });

  describe("clicking the destination you are already on", () => {
    it("slides Spaces back to the list without navigating", async () => {
      const user = userEvent.setup();
      mocks.fullPath = "/spaces/$channelId/loops";
      useCurrentChannelStore.setState({ currentChannelId: "chan-1" });
      rememberVisits({
        spaces: { href: "/spaces/chan-1", listOpen: false, spaceId: "chan-1" },
      });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Spaces"));

      expect(useChannelPaneStore.getState().pane).toBe("list");
      expect(mocks.navigate).not.toHaveBeenCalled();
      expect(mocks.navigateToChannel).not.toHaveBeenCalled();
    });

    // The remembered page is where you are, so restoring it would be a no-op
    // that also refuses to take you up to the destination's index.
    it("goes up to the index rather than restoring", async () => {
      const user = userEvent.setup();
      mocks.fullPath = "/inbox/pulls/$reportId";
      rememberVisits({ inbox: { href: "/inbox/pulls/42" } });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Self-driving"));

      expect(mocks.navigateToInbox).toHaveBeenCalledOnce();
      expect(mocks.navigate).not.toHaveBeenCalled();
    });
  });

  it("peeks at the feed on hover while Activity is somewhere else", async () => {
    const user = userEvent.setup();
    render(<NavRail />);

    await user.hover(screen.getByLabelText("Activity"));

    expect(
      await screen.findByText("Recent activity card", {}, { timeout: 1_000 }),
    ).toBeInTheDocument();
  });

  it("drops the peek once Activity is the destination", async () => {
    const user = userEvent.setup();
    mocks.fullPath = "/activity";
    render(<NavRail />);

    const bell = screen.getByLabelText("Activity");
    expect(bell).not.toHaveAttribute("aria-haspopup");
    await user.hover(bell);

    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(screen.queryByText("Recent activity card")).not.toBeInTheDocument();
  });

  it("drops an item hidden in the sidebar settings", () => {
    useSidebarStore.setState({ navItemOverrides: { "command-center": false } });
    render(<NavRail />);

    expect(screen.queryByLabelText("Command Center")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Self-driving")).toBeInTheDocument();
  });

  it("keeps the column's own destinations when everything else is hidden", () => {
    useSidebarStore.setState({
      navItemOverrides: {
        inbox: false,
        activity: false,
        "command-center": false,
        loops: false,
        configure: false,
      },
    });
    render(<NavRail />);

    expect(screen.getByLabelText("Home")).toBeInTheDocument();
    expect(screen.getByLabelText("Spaces")).toBeInTheDocument();
    expect(screen.queryByLabelText("Settings")).not.toBeInTheDocument();
  });

  it("follows a stored order without moving the pinned destinations", () => {
    useSidebarStore.setState({
      navItemOrder: ["command-center", "inbox", "activity"],
    });
    const { container } = render(<NavRail />);

    // Search leads the rail and is not a destination, so it sits outside the
    // customizable order.
    const labels = [...container.querySelectorAll("button")]
      .map((button) => button.getAttribute("aria-label"))
      .filter((label) => label !== "Search");
    expect(labels.slice(0, 5)).toEqual([
      "Home",
      "Spaces",
      "Command Center",
      "Self-driving",
      "Activity",
    ]);
  });

  it("lights the last square of the Spaces mark while a space is open", () => {
    useCurrentChannelStore.setState({ currentChannelId: "chan-1" });
    useChannelPaneStore.setState({ pane: "channel" });
    const { container, rerender } = render(<NavRail />);
    const lit = () =>
      container.querySelectorAll('rect[fill="var(--primary)"]').length;

    expect(lit()).toBe(1);

    act(() => useChannelPaneStore.setState({ pane: "list" }));
    rerender(<NavRail />);

    expect(lit()).toBe(0);
  });
});
