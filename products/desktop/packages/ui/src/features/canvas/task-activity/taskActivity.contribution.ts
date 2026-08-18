import type { Contribution } from "@posthog/di/contribution";
import type { Task, TaskActivityPage } from "@posthog/shared/domain-types";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";
import {
  NotificationBus,
  type TaskActivitySignal,
} from "@posthog/ui/features/notifications/notifications";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { logger } from "@posthog/ui/shell/logger";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";
import type { InfiniteData } from "@tanstack/react-query";
import { inject, injectable } from "inversify";
import { TASK_ACTIVITY_QUERY_KEY } from "./taskActivityQuery";

const log = logger.scope("task-activity");

@injectable()
export class TaskActivityContribution implements Contribution {
  constructor(
    @inject(NotificationBus)
    private readonly notificationBus: NotificationBus,
    @inject(IMPERATIVE_QUERY_CLIENT)
    private readonly queryClient: ImperativeQueryClient,
  ) {}

  start(): void {
    this.notificationBus.subscribeToTaskActivity((signal) => {
      this.apply(signal);
      if (!signal.isUnread) this.persistRead(signal);
    });
  }

  // A born-read row only exists in this session's cache; without advancing
  // the server's read cursor too, the activity comes back unread on the next
  // cold load even though the user watched it happen.
  private persistRead(signal: TaskActivitySignal): void {
    getAuthenticatedClient()
      .then((client) =>
        client?.markTaskActivityRead([
          { task_id: signal.taskId, seen_before: signal.activityAt },
        ]),
      )
      .catch((error) => {
        log.warn("Failed to persist watched task activity as read", { error });
      });
  }

  private apply(signal: TaskActivitySignal): void {
    const activityQuery = this.queryClient.getQueryCache().find({
      queryKey: TASK_ACTIVITY_QUERY_KEY,
      exact: true,
    });
    if (activityQuery?.meta?.authScoped !== true) return;

    this.queryClient.setQueryData<InfiniteData<TaskActivityPage>>(
      TASK_ACTIVITY_QUERY_KEY,
      (data) => {
        const previous = data?.pages
          .flatMap((page) => page.results)
          .find((row) => row.task_id === signal.taskId);
        const cachedTask =
          this.queryClient.getQueryData<Task>(taskKeys.detail(signal.taskId)) ??
          this.queryClient
            .getQueriesData<Task[]>({ queryKey: taskKeys.lists() })
            .flatMap(([, tasks]) => tasks ?? [])
            .find((task) => task.id === signal.taskId);
        const activity = {
          id: `local:${signal.taskId}`,
          task_id: signal.taskId,
          task_title: signal.taskTitle,
          channel_id: previous
            ? (previous.channel_id ?? null)
            : (cachedTask?.channel ?? null),
          channel_name: previous?.channel_name ?? null,
          activity_at: signal.activityAt,
          activity_kind: signal.activityKind,
          snippet: "",
          latest_author: null,
          latest_message_id: null,
          is_unread: signal.isUnread,
        };
        if (!data) {
          return {
            pages: [
              { results: [activity], unread_count: signal.isUnread ? 1 : 0 },
            ],
            pageParams: [undefined],
          };
        }
        const unreadDelta =
          Number(signal.isUnread) - Number(previous?.is_unread ?? false);
        return {
          ...data,
          pages: data.pages.map((page, index) => ({
            ...page,
            unread_count:
              index === 0
                ? Math.max(0, page.unread_count + unreadDelta)
                : page.unread_count,
            results:
              index === 0
                ? [
                    activity,
                    ...page.results.filter(
                      (row) => row.task_id !== signal.taskId,
                    ),
                  ]
                : page.results.filter((row) => row.task_id !== signal.taskId),
          })),
        };
      },
    );
  }
}
