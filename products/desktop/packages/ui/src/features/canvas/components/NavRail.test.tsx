import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  featureFlags: new Map<string, boolean>(),
  fullPath: "/",
  navigate: vi.fn(),
  navigateToActivity: vi.fn(),
  navigateToSpaces: vi.fn(),
  navigateToChannel: vi.fn(),
  navigateToHome: vi.fn(),
  navigateToInbox: vi.fn(),
}));

vi.mock("@tanstack/react-router", () => ({
  useRouterState: ({
    select,
  }: {
    select: (s: { matches: { fullPath: string }[] }) => unknown;
  }) => select({ matches: [{ fullPath: mocks.fullPath }] }),
}));
vi.mock("@posthog/ui/router/routerRef", () => ({
  getRouterOrNull: () => ({ navigate: mocks.navigate }),
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
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/ui/features/inbox/hooks/useInboxAllReports", () => ({
  useInboxAllReports: () => ({ counts: { pulls: 0 } }),
}));
vi.mock("@posthog/ui/features/sidebar/components/ProjectSwitcher", () => ({
  ProjectSwitcher: () => null,
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
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/canvas/components/ActivityHoverCard", () => ({
  ActivityHoverCard: () => <div>Recent activity card</div>,
}));

import { DESKTOP_HOME_FLAG } from "@posthog/shared";
import {
  clearKeepListForRoute,
  shouldKeepListForRoute,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useRailHistoryStore } from "@posthog/ui/features/canvas/stores/railHistoryStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { NavRail } from "./NavRail";

describe("NavRail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.featureFlags.clear();
    mocks.featureFlags.set(DESKTOP_HOME_FLAG, true);
    mocks.fullPath = "/";
    useSidebarStore.setState({ navItemOverrides: {}, navItemOrder: [] });
    useCurrentChannelStore.setState({ currentChannelId: null });
    useChannelPaneStore.setState({ pane: "channel" });
    useRailHistoryStore.setState({ lastByPane: {} });
    clearKeepListForRoute();
  });

  it("hides Home when its feature flag is off", () => {
    mocks.featureFlags.set(DESKTOP_HOME_FLAG, false);

    render(<NavRail />);

    expect(screen.queryByLabelText("Home")).not.toBeInTheDocument();
  });

  // The route is the whole answer, so a destination can never be lit over a
  // screen that isn't it.
  it.each([
    ["/", "Home"],
    ["/activity", "Activity"],
    ["/inbox/pulls/$reportId", "Inbox"],
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
      useRailHistoryStore.setState({
        lastByPane: {
          spaces: {
            href: "/spaces/chan-1/loops",
            spaces: { listOpen: false, spaceId: "chan-1" },
          },
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
      useRailHistoryStore.setState({
        lastByPane: {
          spaces: {
            href: "/spaces/chan-1/tasks/task-1",
            spaces: { listOpen: true, spaceId: "chan-1" },
          },
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
      useRailHistoryStore.setState({
        lastByPane: {
          spaces: { href: "/spaces", spaces: { listOpen: true } },
        },
      });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Spaces"));

      expect(useChannelPaneStore.getState().pane).toBe("list");
    });

    it("returns to the space pane when the list was not open", async () => {
      const user = userEvent.setup();
      useChannelPaneStore.setState({ pane: "list" });
      useRailHistoryStore.setState({
        lastByPane: {
          spaces: {
            href: "/spaces/chan-1",
            spaces: { listOpen: false, spaceId: "chan-1" },
          },
        },
      });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Spaces"));

      expect(useChannelPaneStore.getState().pane).toBe("channel");
    });

    it("remembers each destination separately", async () => {
      const user = userEvent.setup();
      mocks.fullPath = "/";
      useRailHistoryStore.setState({
        lastByPane: {
          inbox: { href: "/inbox/pulls/42" },
          loops: { href: "/loops/abc" },
        },
      });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Inbox"));

      expect(mocks.navigate).toHaveBeenCalledWith({ href: "/inbox/pulls/42" });
      expect(mocks.navigateToInbox).not.toHaveBeenCalled();
    });
  });

  describe("clicking the destination you are already on", () => {
    it("slides Spaces back to the list without navigating", async () => {
      const user = userEvent.setup();
      mocks.fullPath = "/spaces/$channelId/loops";
      useCurrentChannelStore.setState({ currentChannelId: "chan-1" });
      useRailHistoryStore.setState({
        lastByPane: {
          spaces: {
            href: "/spaces/chan-1",
            spaces: { listOpen: false, spaceId: "chan-1" },
          },
        },
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
      useRailHistoryStore.setState({
        lastByPane: { inbox: { href: "/inbox/pulls/42" } },
      });
      render(<NavRail />);

      await user.click(screen.getByLabelText("Inbox"));

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
    expect(screen.getByLabelText("Inbox")).toBeInTheDocument();
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

    const labels = [...container.querySelectorAll("button")].map((button) =>
      button.getAttribute("aria-label"),
    );
    expect(labels.slice(0, 5)).toEqual([
      "Home",
      "Spaces",
      "Command Center",
      "Inbox",
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
