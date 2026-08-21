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
    useNavRailStore.setState({ pane: "channels" });
  });

  it("hands the sidebar column to Activity without leaving the current screen", async () => {
    const user = userEvent.setup();
    render(<NavRail />);

    await user.click(screen.getByLabelText("Activity"));

    expect(useNavRailStore.getState().pane).toBe("activity");
    expect(mocks.navigateToHome).not.toHaveBeenCalled();
    expect(mocks.navigateToInbox).not.toHaveBeenCalled();
  });

  it("gives the column back to the channel tree from Home", async () => {
    const user = userEvent.setup();
    useNavRailStore.setState({ pane: "activity" });
    render(<NavRail />);

    await user.click(screen.getByLabelText("Home"));

    expect(useNavRailStore.getState().pane).toBe("channels");
    expect(mocks.navigateToHome).toHaveBeenCalledOnce();
  });

  it("lights Activity for a deep link to the activity page", () => {
    mocks.view = { type: "activity" };
    render(<NavRail />);

    expect(screen.getByLabelText("Activity")).toHaveAttribute(
      "data-selected",
      "true",
    );
    expect(screen.getByLabelText("Home")).not.toHaveAttribute("data-selected");
  });

  it("keeps Home lit while a channel or task is open", () => {
    mocks.view = { type: "task-detail" };
    render(<NavRail />);

    expect(screen.getByLabelText("Home")).toHaveAttribute(
      "data-selected",
      "true",
    );
  });
});
