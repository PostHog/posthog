import type { INotifications } from "@posthog/platform/notifications";
import type { TaskActivityPage } from "@posthog/shared/domain-types";
import type {
  INotificationSettings,
  NotificationSettings,
} from "@posthog/ui/features/notifications/identifiers";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { registerRendererStateStorage } from "@posthog/ui/shell/rendererStorage";
import { type InfiniteData, QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DockBadgeContribution } from "./dockBadge.contribution";
import { TASK_ACTIVITY_QUERY_KEY } from "./taskActivityQuery";

registerRendererStateStorage({
  getItem: vi.fn().mockResolvedValue(null),
  setItem: vi.fn().mockResolvedValue(undefined),
  removeItem: vi.fn().mockResolvedValue(undefined),
});

function page(unreadCount: number): InfiniteData<TaskActivityPage> {
  return {
    pages: [{ results: [], unread_count: unreadCount }],
    pageParams: [undefined],
  };
}

// Mirrors the real host adapters (desktop-services.ts, web-notifications.ts):
// dockBadgeNotifications is read live off the shared store, not a snapshot,
// so tests can exercise the contribution's store subscription the same way
// production settings toggles do.
function makeSettings(): INotificationSettings {
  const settings: Omit<NotificationSettings, "dockBadgeNotifications"> = {
    desktopNotifications: true,
    dockBounceNotifications: true,
    completionSound: "meep",
    completionVolume: 80,
    scaleSoundWithTaskLength: false,
    customSounds: [],
  };
  return {
    get: () => ({
      ...settings,
      dockBadgeNotifications:
        useSettingsStore.getState().dockBadgeNotifications,
    }),
  };
}

describe("DockBadgeContribution", () => {
  let queryClient: QueryClient;
  let notifications: INotifications;

  beforeEach(() => {
    queryClient = new QueryClient();
    notifications = {
      notify: vi.fn(),
      setBadgeCount: vi.fn(),
      requestAttention: vi.fn(),
    };
    useSettingsStore.setState({ dockBadgeNotifications: true });
  });

  it("pushes the cached unread count on start", () => {
    queryClient.setQueryData(TASK_ACTIVITY_QUERY_KEY, page(3));

    new DockBadgeContribution(
      queryClient,
      notifications,
      makeSettings(),
    ).start();

    expect(notifications.setBadgeCount).toHaveBeenCalledWith(3);
  });

  it("pushes 0 when dock badge notifications are disabled, regardless of unread count", () => {
    queryClient.setQueryData(TASK_ACTIVITY_QUERY_KEY, page(5));
    useSettingsStore.setState({ dockBadgeNotifications: false });

    new DockBadgeContribution(
      queryClient,
      notifications,
      makeSettings(),
    ).start();

    expect(notifications.setBadgeCount).toHaveBeenCalledWith(0);
  });

  it("resyncs when the dockBadgeNotifications setting changes, not just on cache updates", () => {
    queryClient.setQueryData(TASK_ACTIVITY_QUERY_KEY, page(3));
    new DockBadgeContribution(
      queryClient,
      notifications,
      makeSettings(),
    ).start();
    vi.mocked(notifications.setBadgeCount).mockClear();

    useSettingsStore.setState({ dockBadgeNotifications: false });
    expect(notifications.setBadgeCount).toHaveBeenCalledWith(0);

    useSettingsStore.setState({ dockBadgeNotifications: true });
    expect(notifications.setBadgeCount).toHaveBeenCalledWith(3);
  });

  it("updates the badge when the unread count changes after start", () => {
    queryClient.setQueryData(TASK_ACTIVITY_QUERY_KEY, page(1));
    new DockBadgeContribution(
      queryClient,
      notifications,
      makeSettings(),
    ).start();
    vi.mocked(notifications.setBadgeCount).mockClear();

    queryClient.setQueryData(TASK_ACTIVITY_QUERY_KEY, page(4));

    expect(notifications.setBadgeCount).toHaveBeenCalledWith(4);
  });

  it("does not push again when the count hasn't changed", () => {
    queryClient.setQueryData(TASK_ACTIVITY_QUERY_KEY, page(2));
    new DockBadgeContribution(
      queryClient,
      notifications,
      makeSettings(),
    ).start();
    vi.mocked(notifications.setBadgeCount).mockClear();

    queryClient.setQueryData(TASK_ACTIVITY_QUERY_KEY, page(2));

    expect(notifications.setBadgeCount).not.toHaveBeenCalled();
  });
});
