import type { Contribution } from "@posthog/di/contribution";
import {
  type INotifications,
  NOTIFICATIONS_SERVICE,
} from "@posthog/platform/notifications";
import type { TaskActivityPage } from "@posthog/shared/domain-types";
import {
  type INotificationSettings,
  NOTIFICATION_SETTINGS_PROVIDER,
} from "@posthog/ui/features/notifications/identifiers";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";
import { hashKey, type InfiniteData } from "@tanstack/react-query";
import { inject, injectable } from "inversify";
import { TASK_ACTIVITY_QUERY_KEY } from "./taskActivityQuery";

const TASK_ACTIVITY_QUERY_HASH = hashKey(TASK_ACTIVITY_QUERY_KEY);

// Keeps the native dock/taskbar badge equal to the same unread count the
// sidebar Activity badge shows, so the two never disagree. Reads the cache
// directly (rather than reacting to individual notify() calls) because the
// count also has to fall as items are read, not just rise as they arrive.
@injectable()
export class DockBadgeContribution implements Contribution {
  private lastPushedCount: number | undefined;

  constructor(
    @inject(IMPERATIVE_QUERY_CLIENT)
    private readonly queryClient: ImperativeQueryClient,
    @inject(NOTIFICATIONS_SERVICE)
    private readonly notifications: INotifications,
    @inject(NOTIFICATION_SETTINGS_PROVIDER)
    private readonly settings: INotificationSettings,
  ) {}

  start(): void {
    this.sync();
    // queryHash compares by value (unlike the queryKey array reference), so
    // this only reacts to the task-activity query instead of scanning the
    // whole cache on every unrelated query event in the app.
    this.queryClient.getQueryCache().subscribe((event) => {
      if (event.query.queryHash !== TASK_ACTIVITY_QUERY_HASH) return;
      this.sync();
    });
    // INotificationSettings only exposes a snapshot getter, with no way to
    // learn a setting changed, so toggling "dock badge notifications" here
    // wouldn't otherwise resync until the next unrelated cache write.
    useSettingsStore.subscribe((state, prev) => {
      if (state.dockBadgeNotifications !== prev.dockBadgeNotifications) {
        this.sync();
      }
    });
  }

  private sync(): void {
    const query = this.queryClient
      .getQueryCache()
      .get(TASK_ACTIVITY_QUERY_HASH);
    const data = query?.state.data as
      | InfiniteData<TaskActivityPage>
      | undefined;
    const count = this.settings.get().dockBadgeNotifications
      ? (data?.pages[0]?.unread_count ?? 0)
      : 0;
    if (count === this.lastPushedCount) return;
    this.lastPushedCount = count;
    this.notifications.setBadgeCount(count);
  }
}
