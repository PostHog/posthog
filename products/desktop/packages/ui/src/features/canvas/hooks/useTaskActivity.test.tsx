import type {
  TaskActivity,
  TaskActivityPage,
} from "@posthog/shared/domain-types";
import {
  focusManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockClient = vi.hoisted(() => ({
  getTaskActivity: vi.fn(),
  markTaskActivityRead: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => mockClient,
}));

import { useMarkTaskActivityRead } from "./useMarkTaskActivityRead";
import { TASK_ACTIVITY_QUERY_KEY, useTaskActivity } from "./useTaskActivity";

function activity(overrides: Partial<TaskActivity>): TaskActivity {
  return {
    id: "activity-1",
    task_id: "task-1",
    task_title: "Task",
    activity_at: "2026-07-01T10:00:00Z",
    activity_kind: "mention",
    snippet: "Ping",
    is_unread: true,
    ...overrides,
  };
}

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("task activity hooks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  afterEach(() => {
    queryClient.clear();
    focusManager.setFocused(undefined);
  });

  it("loads every activity page", async () => {
    mockClient.getTaskActivity
      .mockResolvedValueOnce({
        results: [activity({ task_id: "task-2" })],
        unread_count: 2,
        next_before: "2026-07-01T10:00:00Z",
        next_before_id: "activity-1",
      })
      .mockResolvedValueOnce({
        results: [
          activity({
            id: "activity-2",
            task_id: "task-1",
            activity_at: "2026-06-30T10:00:00Z",
          }),
        ],
        unread_count: 2,
        next_before: null,
        next_before_id: null,
      });

    const hook = renderHook(() => useTaskActivity(), { wrapper });
    await waitFor(() => expect(hook.result.current.items).toHaveLength(1));
    await act(async () => {
      await hook.result.current.fetchNextPage();
    });

    await waitFor(() =>
      expect(hook.result.current.items.map((item) => item.taskId)).toEqual([
        "task-2",
        "task-1",
      ]),
    );
    expect(mockClient.getTaskActivity).toHaveBeenLastCalledWith({
      before: "2026-07-01T10:00:00Z",
      beforeId: "activity-1",
    });
  });

  it.each([
    [
      "the app regains focus",
      (): void => {
        act(() => focusManager.setFocused(false));
        act(() => focusManager.setFocused(true));
      },
    ],
    [
      "an Activity surface opens",
      (): void => {
        renderHook(() => useTaskActivity(), { wrapper });
      },
    ],
  ])("refreshes activity when %s", async (_name, refresh) => {
    mockClient.getTaskActivity
      .mockResolvedValueOnce({ results: [], unread_count: 0 })
      .mockResolvedValueOnce({
        results: [
          activity({
            id: "comment-activity-1",
            latest_comment_id: "comment-1",
          }),
        ],
        unread_count: 1,
      });

    const hook = renderHook(() => useTaskActivity(), { wrapper });
    await waitFor(() =>
      expect(mockClient.getTaskActivity).toHaveBeenCalledOnce(),
    );
    expect(hook.result.current.items).toEqual([]);

    refresh();

    await waitFor(() =>
      expect(hook.result.current.items[0]).toMatchObject({
        id: "comment-activity-1",
        commentId: "comment-1",
      }),
    );
    expect(mockClient.getTaskActivity).toHaveBeenCalledTimes(2);
    expect(hook.result.current.unreadCount).toBe(1);
  });

  it("does not optimistically clear activity newer than the marker", async () => {
    const page: TaskActivityPage = {
      results: [activity({ activity_at: "2026-07-01T11:00:00Z" })],
      unread_count: 1,
    };
    queryClient.setQueryData(TASK_ACTIVITY_QUERY_KEY, {
      pages: [page],
      pageParams: [undefined],
    });
    mockClient.markTaskActivityRead.mockResolvedValue({
      marked_read: 0,
      unread_count: 1,
    });

    const hook = renderHook(() => useMarkTaskActivityRead(), { wrapper });
    act(() => {
      hook.result.current.mutate([
        { task_id: "task-1", seen_before: "2026-07-01T10:00:00Z" },
      ]);
    });

    await waitFor(() =>
      expect(mockClient.markTaskActivityRead).toHaveBeenCalledOnce(),
    );
    const cached = queryClient.getQueryData<{
      pages: TaskActivityPage[];
    }>(TASK_ACTIVITY_QUERY_KEY);
    expect(cached?.pages[0]?.results[0]?.is_unread).toBe(true);
    expect(cached?.pages[0]?.unread_count).toBe(1);
  });

  it("keeps an activity row after marking it read", async () => {
    mockClient.getTaskActivity.mockResolvedValue({
      results: [activity({ id: "local:task-1" })],
      unread_count: 1,
    });
    mockClient.markTaskActivityRead.mockResolvedValue({
      marked_read: 0,
      unread_count: 0,
    });

    const hook = renderHook(
      () => ({ activity: useTaskActivity(), mark: useMarkTaskActivityRead() }),
      { wrapper },
    );
    await waitFor(() =>
      expect(hook.result.current.activity.items).toHaveLength(1),
    );

    act(() => {
      hook.result.current.mark.mutate([
        { task_id: "task-1", seen_before: "2026-07-01T10:00:00Z" },
      ]);
    });

    await waitFor(() =>
      expect(hook.result.current.activity.unreadCount).toBe(0),
    );
    expect(hook.result.current.activity.items).toHaveLength(1);
    expect(mockClient.getTaskActivity).toHaveBeenCalledOnce();
  });

  it("marks only the selected comment activity read", async () => {
    const page: TaskActivityPage = {
      results: [
        activity({
          id: "comment-activity-1",
          latest_comment_id: "comment-1",
        }),
        activity({
          id: "comment-activity-2",
          latest_comment_id: "comment-2",
        }),
        activity({
          id: "task-activity",
          activity_kind: "awaiting_input",
          latest_comment_id: null,
        }),
      ],
      unread_count: 3,
    };
    queryClient.setQueryData(TASK_ACTIVITY_QUERY_KEY, {
      pages: [page],
      pageParams: [undefined],
    });
    mockClient.markTaskActivityRead.mockResolvedValue({
      marked_read: 1,
      unread_count: 1,
    });

    const hook = renderHook(() => useMarkTaskActivityRead(), { wrapper });
    act(() => {
      hook.result.current.mutate([
        {
          task_id: "task-1",
          seen_before: "2026-07-01T10:00:00Z",
          activity_id: "comment-activity-1",
        },
      ]);
    });

    await waitFor(() =>
      expect(mockClient.markTaskActivityRead).toHaveBeenCalledOnce(),
    );
    const cached = queryClient.getQueryData<{
      pages: TaskActivityPage[];
    }>(TASK_ACTIVITY_QUERY_KEY);
    expect(cached?.pages[0]?.results.map((row) => row.is_unread)).toEqual([
      false,
      true,
      true,
    ]);
    expect(cached?.pages[0]?.unread_count).toBe(2);
  });
});
