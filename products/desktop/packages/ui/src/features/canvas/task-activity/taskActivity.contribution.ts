import type { Contribution } from "@posthog/di/contribution";
import type { Task, TaskActivityPage } from "@posthog/shared/domain-types";
import {
  NotificationBus,
  type TaskActivitySignal,
} from "@posthog/ui/features/notifications/notifications";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";
import type { InfiniteData } from "@tanstack/react-query";
import { inject, injectable } from "inversify";
import { TASK_ACTIVITY_QUERY_KEY } from "./taskActivityQuery";

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
          is_unread: true,
        };
        if (!data) {
          return {
            pages: [{ results: [activity], unread_count: 1 }],
            pageParams: [undefined],
          };
        }
        const unreadIncrement = previous?.is_unread ? 0 : 1;
        return {
          ...data,
          pages: data.pages.map((page, index) => ({
            ...page,
            unread_count:
              index === 0
                ? page.unread_count + unreadIncrement
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
