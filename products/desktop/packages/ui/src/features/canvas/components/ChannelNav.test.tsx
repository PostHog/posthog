import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  view: { type: "task-input" },
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
vi.mock("@posthog/ui/router/useAppView", () => ({
  useAppView: () => mocks.view,
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToActivity: vi.fn(),
  navigateToInbox: vi.fn(),
  navigateToWebsiteCommandCenter: vi.fn(),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("./ActivityHoverCard", () => ({
  ActivityHoverCard: () => <div>Recent activity card</div>,
}));

import { ChannelNav } from "./ChannelNav";

describe("ChannelNav", () => {
  beforeEach(() => {
    mocks.view = { type: "task-input" };
  });

  it("opens recent activity from the bell after the hover delay", async () => {
    const user = userEvent.setup();
    render(<ChannelNav />);

    await user.hover(screen.getByLabelText("Activity"));
    expect(screen.queryByText("Recent activity card")).not.toBeInTheDocument();

    expect(
      await screen.findByText("Recent activity card", {}, { timeout: 1_000 }),
    ).toBeInTheDocument();
  });

  it("closes promptly after the pointer leaves", async () => {
    const user = userEvent.setup();
    render(<ChannelNav />);
    const activity = screen.getByLabelText("Activity");

    await user.hover(activity);
    await screen.findByText("Recent activity card", {}, { timeout: 1_000 });
    await user.unhover(activity);

    await waitFor(() =>
      expect(
        screen.queryByText("Recent activity card"),
      ).not.toBeInTheDocument(),
    );
  });

  it("does not open the hover card on the Activity page", async () => {
    mocks.view = { type: "activity" };
    const user = userEvent.setup();
    render(<ChannelNav />);

    const activity = screen.getByLabelText("Activity");
    expect(activity).toBeEnabled();
    await user.hover(activity);

    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(screen.queryByText("Recent activity card")).not.toBeInTheDocument();
  });
});
