import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  unreadCount: 0,
  notifications: { setUnreadCount: vi.fn() },
}));

vi.mock("@posthog/ui/features/canvas/hooks/useTaskActivity", () => ({
  useTaskActivity: () => ({ unreadCount: mocks.unreadCount }),
}));

vi.mock("@posthog/di/react", () => ({
  useServiceOptional: () => mocks.notifications,
}));

import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useDockBadgeSync } from "./useDockBadgeSync";

describe("useDockBadgeSync", () => {
  beforeEach(() => {
    mocks.notifications = { setUnreadCount: vi.fn() };
    mocks.unreadCount = 0;
    useSettingsStore.setState({ dockBadgeNotifications: true });
  });

  it("pushes the count, then zero once it drops so the badge can clear", () => {
    mocks.unreadCount = 5;
    const { rerender } = renderHook(() => useDockBadgeSync());
    expect(mocks.notifications.setUnreadCount).toHaveBeenCalledWith(5);

    mocks.unreadCount = 0;
    rerender();

    expect(mocks.notifications.setUnreadCount).toHaveBeenLastCalledWith(0);
  });

  it("pushes zero while the setting is off, and the count again once back on", () => {
    mocks.unreadCount = 5;
    useSettingsStore.setState({ dockBadgeNotifications: false });
    renderHook(() => useDockBadgeSync());
    expect(mocks.notifications.setUnreadCount).toHaveBeenCalledWith(0);

    act(() => {
      useSettingsStore.setState({ dockBadgeNotifications: true });
    });

    expect(mocks.notifications.setUnreadCount).toHaveBeenLastCalledWith(5);
  });

  it("clears the badge on unmount, so signing out leaves no stale count", () => {
    mocks.unreadCount = 5;
    const { unmount } = renderHook(() => useDockBadgeSync());

    unmount();

    expect(mocks.notifications.setUnreadCount).toHaveBeenLastCalledWith(0);
  });
});
