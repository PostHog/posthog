import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  view: { type: "home" } as { type: string },
  pathname: "/website/home",
  navigateToActivity: vi.fn(),
  navigateToHome: vi.fn(),
  navigateToInbox: vi.fn(),
}));

vi.mock("@tanstack/react-router", () => ({
  useRouterState: ({
    select,
  }: {
    select: (s: { location: { pathname: string } }) => unknown;
  }) => select({ location: { pathname: mocks.pathname } }),
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
vi.mock("@posthog/ui/features/inbox/hooks/useInboxAllReports", () => ({
  useInboxAllReports: () => ({ counts: { pulls: 0 } }),
}));
vi.mock("@posthog/ui/features/sidebar/components/ProjectSwitcher", () => ({
  ProjectSwitcher: () => null,
}));
vi.mock("@posthog/ui/router/useAppView", () => ({
  useAppView: () => mocks.view,
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToActivity: (...args: unknown[]) => mocks.navigateToActivity(...args),
  navigateToHome: (...args: unknown[]) => mocks.navigateToHome(...args),
  navigateToInbox: (...args: unknown[]) => mocks.navigateToInbox(...args),
  navigateToLoops: vi.fn(),
  navigateToWebsiteCommandCenter: vi.fn(),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/canvas/components/ActivityHoverCard", () => ({
  ActivityHoverCard: () => <div>Recent activity card</div>,
}));

import { useChannelPaneStore } from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useNavRailStore } from "@posthog/ui/features/canvas/stores/navRailStore";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { NavRail } from "./NavRail";

describe("NavRail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.view = { type: "home" };
    mocks.pathname = "/website/home";
    useNavRailStore.setState({ pane: "spaces" });
    useSidebarStore.setState({ navItemOverrides: {}, navItemOrder: [] });
  });

  it("hands the sidebar column to Activity without leaving the current screen", async () => {
    const user = userEvent.setup();
    render(<NavRail />);

    await user.click(screen.getByLabelText("Activity"));

    expect(useNavRailStore.getState().pane).toBe("activity");
    expect(mocks.navigateToActivity).not.toHaveBeenCalled();
    expect(mocks.navigateToHome).not.toHaveBeenCalled();
    expect(mocks.navigateToInbox).not.toHaveBeenCalled();
  });

  it("moves into the space tree when Activity is picked from outside it", async () => {
    const user = userEvent.setup();
    mocks.pathname = "/code/inbox";
    mocks.view = { type: "inbox" };
    render(<NavRail />);

    await user.click(screen.getByLabelText("Activity"));

    expect(useNavRailStore.getState().pane).toBe("activity");
    expect(mocks.navigateToActivity).toHaveBeenCalledOnce();
  });

  it("shows the space tree without routing to a space", async () => {
    const user = userEvent.setup();
    mocks.view = { type: "activity" };
    render(<NavRail />);

    await user.click(screen.getByLabelText("Spaces"));

    expect(useNavRailStore.getState().pane).toBe("spaces");
    expect(mocks.navigateToHome).not.toHaveBeenCalled();
  });

  it("slides back to the list when a space is already open", async () => {
    const user = userEvent.setup();
    useChannelPaneStore.setState({ pane: "channel" });
    render(<NavRail />);

    await user.click(screen.getByLabelText("Spaces"));

    expect(useChannelPaneStore.getState().pane).toBe("list");
  });

  it("keeps a route-free pick from snapping back to the route behind it", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<NavRail />);

    await user.click(screen.getByLabelText("Spaces"));
    rerender(<NavRail />);

    expect(useNavRailStore.getState().pane).toBe("spaces");
  });

  it("follows the route when the route is what moved", () => {
    mocks.view = { type: "activity" };
    render(<NavRail />);

    expect(useNavRailStore.getState().pane).toBe("activity");
    expect(screen.getByLabelText("Activity")).toHaveAttribute(
      "data-selected",
      "true",
    );
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
    mocks.view = { type: "activity" };
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

  it("counts a channel or task as part of Spaces", () => {
    mocks.view = { type: "task-detail" };
    render(<NavRail />);

    expect(screen.getByLabelText("Spaces")).toHaveAttribute(
      "data-selected",
      "true",
    );
    expect(screen.getByLabelText("Home")).not.toHaveAttribute("data-selected");
  });
});
