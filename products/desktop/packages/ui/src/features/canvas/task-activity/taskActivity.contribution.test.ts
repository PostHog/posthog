import type { TaskActivityPage } from "@posthog/shared/domain-types";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import type {
  NotificationBus,
  TaskActivitySignal,
} from "@posthog/ui/features/notifications/notifications";
import { type InfiniteData, QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TaskActivityContribution } from "./taskActivity.contribution";

let activityListener: ((signal: TaskActivitySignal) => void) | undefined;
const notificationBus = {
  subscribeToTaskActivity: vi.fn(
    (listener: (signal: TaskActivitySignal) => void) => {
      activityListener = listener;
      return vi.fn();
    },
  ),
} as unknown as NotificationBus;

describe("TaskActivityContribution", () => {
  let queryClient: QueryClient;
  let contribution: TaskActivityContribution;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient();
    contribution = new TaskActivityContribution(notificationBus, queryClient);
    contribution.start();
  });

  it("shows task activity immediately when its backend projection is not available yet", () => {
    queryClient.setQueryDefaults(["task-activity"], {
      meta: AUTH_SCOPED_QUERY_META,
    });
    queryClient.setQueryData<InfiniteData<TaskActivityPage>>(
      ["task-activity"],
      {
        pages: [{ results: [], unread_count: 0 }],
        pageParams: [undefined],
      },
    );

    activityListener?.({
      taskId: "task-1",
      taskTitle: "Channel task",
      activityKind: "awaiting_input",
      activityAt: "2026-07-27T10:00:00Z",
    });

    const cached = queryClient.getQueryData<InfiniteData<TaskActivityPage>>([
      "task-activity",
    ]);
    expect(cached?.pages[0]).toMatchObject({
      unread_count: 1,
      results: [
        {
          task_id: "task-1",
          task_title: "Channel task",
          activity_kind: "awaiting_input",
          is_unread: true,
        },
      ],
    });
  });

  it("does not recreate activity data after the authenticated query is removed", () => {
    activityListener?.({
      taskId: "task-1",
      taskTitle: "Previous user's task",
      activityKind: "completed",
      activityAt: "2026-07-27T10:00:00Z",
    });

    expect(queryClient.getQueryData(["task-activity"])).toBeUndefined();
  });
});
