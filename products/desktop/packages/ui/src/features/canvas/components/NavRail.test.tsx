import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  view: { type: "home" } as { type: string },
  navigateToHome: vi.fn(),
  navigateToInbox: vi.fn(),
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
  navigateToHome: (...args: unknown[]) => mocks.navigateToHome(...args),
  navigateToInbox: (...args: unknown[]) => mocks.navigateToInbox(...args),
  navigateToLoops: vi.fn(),
  navigateToWebsiteCommandCenter: vi.fn(),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { useNavRailStore } from "@posthog/ui/features/canvas/stores/navRailStore";
import { NavRail } from "./NavRail";

describe("NavRail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.view = { type: "home" };
    useNavRailStore.setState({ pane: "spaces" });
  });

  it("hands the sidebar column to Activity without leaving the current screen", async () => {
    const user = userEvent.setup();
    render(<NavRail />);

    await user.click(screen.getByLabelText("Activity"));

    expect(useNavRailStore.getState().pane).toBe("activity");
    expect(mocks.navigateToHome).not.toHaveBeenCalled();
    expect(mocks.navigateToInbox).not.toHaveBeenCalled();
  });

  it("shows the space tree without routing to a space", async () => {
    const user = userEvent.setup();
    useNavRailStore.setState({ pane: "activity" });
    render(<NavRail />);

    await user.click(screen.getByLabelText("Spaces"));

    expect(useNavRailStore.getState().pane).toBe("spaces");
    expect(mocks.navigateToHome).not.toHaveBeenCalled();
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
