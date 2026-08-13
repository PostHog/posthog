import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  view: { type: "task-input" },
  homeEnabled: false,
  navigateToHome: vi.fn(),
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
  navigateToHome: mocks.navigateToHome,
  navigateToInbox: vi.fn(),
  navigateToWebsiteCommandCenter: vi.fn(),
}));
vi.mock("@posthog/ui/features/home/useHomeEnabled", () => ({
  useHomeEnabled: () => mocks.homeEnabled,
}));
// The real hook reads the host tRPC context, which this nav row has no
// provider for; Home's prefetch is exercised where the page itself is.
vi.mock("@posthog/ui/features/home/useHomeWork", () => ({
  usePrefetchHomeWork: () => () => {},
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("./ActivityHoverCard", () => ({
  ActivityHoverCard: () => <div>Recent activity card</div>,
}));

import { ChannelNav } from "./ChannelNav";

describe("ChannelNav", () => {
  beforeEach(() => {
    mocks.view = { type: "task-input" };
    mocks.homeEnabled = false;
    mocks.navigateToHome.mockClear();
  });

  it("leaves Home out of the row until its flag is on", () => {
    render(<ChannelNav />);

    expect(screen.queryByLabelText("Home")).not.toBeInTheDocument();
  });

  it("puts Home left of Inbox, and opens it", async () => {
    mocks.homeEnabled = true;
    const user = userEvent.setup();
    render(<ChannelNav />);

    const labels = screen
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label"));
    expect(labels.indexOf("Home")).toBe(labels.indexOf("Inbox") - 1);

    await user.click(screen.getByLabelText("Home"));
    expect(mocks.navigateToHome).toHaveBeenCalled();
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
    expect(activity).not.toHaveAttribute("aria-haspopup");
    await user.hover(activity);

    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(screen.queryByText("Recent activity card")).not.toBeInTheDocument();
  });

  it("leaves no popover state on the bell after it navigates to Activity", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ChannelNav />);
    const bell = () => screen.getByLabelText("Activity");

    await user.hover(bell());
    await screen.findByText("Recent activity card", {}, { timeout: 1_000 });
    await user.click(bell());
    mocks.view = { type: "activity" };
    rerender(<ChannelNav />);

    expect(screen.queryByText("Recent activity card")).not.toBeInTheDocument();
    expect(bell()).not.toHaveAttribute("data-popup-open");
    expect(bell()).not.toHaveAttribute("data-pressed");
  });

  it("neither resurfaces nor wedges the hover card once the bell has navigated", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<ChannelNav />);
    const bell = () => screen.getByLabelText("Activity");

    await user.hover(bell());
    await user.click(bell());
    mocks.view = { type: "activity" };
    rerender(<ChannelNav />);
    await user.unhover(bell());

    mocks.view = { type: "task-detail" };
    rerender(<ChannelNav />);
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(screen.queryByText("Recent activity card")).not.toBeInTheDocument();

    await user.hover(bell());
    expect(
      await screen.findByText("Recent activity card", {}, { timeout: 1_000 }),
    ).toBeInTheDocument();
  });
});
