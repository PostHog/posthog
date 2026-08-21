import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  routeId: "/website/home",
  navigateToActivity: vi.fn(),
  navigateToCanvas: vi.fn(),
  navigateToChannel: vi.fn(),
  navigateToHome: vi.fn(),
  navigateToInbox: vi.fn(),
}));

vi.mock("@tanstack/react-router", () => ({
  useRouterState: ({
    select,
  }: {
    select: (s: { matches: { routeId: string }[] }) => unknown;
  }) => select({ matches: [{ routeId: mocks.routeId }] }),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useTaskActivity", () => ({
  useTaskActivity: () => ({ unreadCount: 1 }),
}));
vi.mock(
  "@posthog/ui/features/command-center/useCommandCenterActiveCount",
  () => ({ useCommandCenterActiveCount: () => 0 }),
);
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
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
  getCurrentMatches: () => [{ routeId: mocks.routeId }],
  navigateToActivity: (...args: unknown[]) => mocks.navigateToActivity(...args),
  navigateToCanvas: (...args: unknown[]) => mocks.navigateToCanvas(...args),
  navigateToChannel: (...args: unknown[]) => mocks.navigateToChannel(...args),
  navigateToHome: (...args: unknown[]) => mocks.navigateToHome(...args),
  navigateToInbox: (...args: unknown[]) => mocks.navigateToInbox(...args),
  navigateToLoops: vi.fn(),
  navigateToWebsiteCommandCenter: vi.fn(),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/canvas/components/ActivityHoverCard", () => ({
  ActivityHoverCard: () => <div>Recent activity card</div>,
}));

import {
  clearKeepListForRoute,
  shouldKeepListForRoute,
  useChannelPaneStore,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { NavRail } from "./NavRail";

describe("NavRail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.routeId = "/website/home";
    useSidebarStore.setState({ navItemOverrides: {}, navItemOrder: [] });
    useCurrentChannelStore.setState({ currentChannelId: null });
    useChannelPaneStore.setState({ pane: "channel" });
    clearKeepListForRoute();
  });

  // The route is the whole answer, so a destination can never be lit over a
  // screen that isn't it.
  it.each([
    ["/website/home", "Home"],
    ["/website/activity", "Activity"],
    ["/code/inbox/pulls/$reportId", "Inbox"],
    ["/website/command-center", "Command Center"],
    ["/website/$channelId/loops", "Spaces"],
    ["/website/$channelId/context", "Spaces"],
    ["/website/$channelId/", "Spaces"],
    ["/website/$channelId/tasks/$taskId", "Spaces"],
  ])("lights %s as %s", (routeId, label) => {
    mocks.routeId = routeId;
    render(<NavRail />);

    expect(screen.getByLabelText(label)).toHaveAttribute(
      "data-selected",
      "true",
    );
  });

  it("routes to Activity from a screen that has no column for it", async () => {
    const user = userEvent.setup();
    mocks.routeId = "/code/inbox";
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

    expect(mocks.navigateToCanvas).toHaveBeenCalledOnce();
    expect(mocks.navigateToChannel).not.toHaveBeenCalled();
  });

  it("only slides back to the list when a space is already on screen", async () => {
    const user = userEvent.setup();
    mocks.routeId = "/website/$channelId/tasks/$taskId";
    useCurrentChannelStore.setState({ currentChannelId: "chan-1" });
    render(<NavRail />);

    await user.click(screen.getByLabelText("Spaces"));

    expect(useChannelPaneStore.getState().pane).toBe("list");
    expect(mocks.navigateToChannel).not.toHaveBeenCalled();
    expect(mocks.navigateToCanvas).not.toHaveBeenCalled();
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
    mocks.routeId = "/website/activity";
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
