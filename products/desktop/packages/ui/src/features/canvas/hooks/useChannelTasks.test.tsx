import type { Task } from "@posthog/shared/domain-types";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { channelFeedQueryKey } from "@posthog/ui/features/canvas/hooks/useChannelFeed";
import { taskKeys } from "@posthog/ui/features/tasks/taskKeys";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

function deferred<T>(): {
  promise: Promise<T>;
  reject: (error: Error) => void;
  resolve: (value: T) => void;
} {
  let reject!: (error: Error) => void;
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

const LIST_PATH = [["channelTasks", "list"]];
const listKey = (channelId: string) => [
  ...LIST_PATH,
  { input: { channelId }, type: "query" },
];

const mutations = vi.hoisted(() => ({
  file: vi.fn().mockResolvedValue({
    taskId: "t1",
    channelId: "dest",
    createdAt: 1,
  }),
  unfile: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    channelTasks: {
      list: {
        pathFilter: () => ({ queryKey: LIST_PATH }),
        queryFilter: ({ channelId }: { channelId: string }) => ({
          queryKey: listKey(channelId),
        }),
      },
      file: {
        mutationOptions: (options: object) => ({
          ...options,
          mutationFn: mutations.file,
        }),
      },
      unfile: {
        mutationOptions: (options: object) => ({
          ...options,
          mutationFn: mutations.unfile,
        }),
      },
    },
  }),
}));

import { useChannelTaskMutations } from "./useChannelTasks";

describe("useChannelTaskMutations", () => {
  let queryClient: QueryClient;

  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  const invalidatedChannels = () =>
    queryClient
      .getQueryCache()
      .getAll()
      .filter(
        (query) =>
          query.state.isInvalidated &&
          Array.isArray(query.queryKey[0]) &&
          query.queryKey[0][0] === "channelTasks",
      )
      .map(
        (query) =>
          (query.queryKey[1] as { input: { channelId: string } }).input
            .channelId,
      )
      .sort();

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    // A user who has browsed around holds a list per channel visited. Only the
    // ones a filed task actually moves between should be refetched.
    queryClient.setQueryData(listKey("source"), [
      { channelId: "source", taskId: "t1", createdAt: 1 },
    ]);
    queryClient.setQueryData(listKey("dest"), [
      { channelId: "dest", taskId: "t2", createdAt: 2 },
    ]);
    queryClient.setQueryData(listKey("unrelated"), [
      { channelId: "unrelated", taskId: "t3", createdAt: 3 },
    ]);
    const task = {
      id: "t1",
      channel: "source",
      title: "Move this task",
    } as Task;
    const destinationTask = {
      id: "t2",
      channel: "dest",
      title: "Destination task",
    } as Task;
    queryClient.setQueryData(taskKeys.list(), [task]);
    queryClient.setQueryData(taskKeys.detail("t1"), task);
    queryClient.setQueryData(channelFeedQueryKey("source"), [task]);
    queryClient.setQueryData(channelFeedQueryKey("dest"), [destinationTask]);
  });

  it("filing a task invalidates only its old and new channel", async () => {
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });

    await act(async () => {
      await result.current.fileTask("dest", "t1");
    });

    expect(invalidatedChannels()).toEqual(["dest", "source"]);
  });

  it("moves a task between cached channels before filing completes", async () => {
    let resolveFile:
      | ((value: {
          taskId: string;
          channelId: string;
          createdAt: number;
        }) => void)
      | null = null;
    mutations.file.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFile = resolve;
        }),
    );
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });
    let filing: Promise<unknown>;

    await act(async () => {
      filing = result.current.fileTask("dest", "t1");
      await Promise.resolve();
    });

    expect(queryClient.getQueryData(listKey("source"))).toEqual([]);
    expect(queryClient.getQueryData(listKey("dest"))).toEqual([
      { channelId: "dest", taskId: "t2", createdAt: 2 },
      { channelId: "dest", taskId: "t1", createdAt: 1 },
    ]);
    expect(queryClient.getQueryData(listKey("unrelated"))).toEqual([
      { channelId: "unrelated", taskId: "t3", createdAt: 3 },
    ]);
    expect(queryClient.getQueryData<Task>(taskKeys.detail("t1"))?.channel).toBe(
      "dest",
    );
    expect(
      queryClient.getQueryData<Task[]>(taskKeys.list())?.[0]?.channel,
    ).toBe("dest");
    expect(queryClient.getQueryData(channelFeedQueryKey("source"))).toEqual([]);
    expect(
      queryClient
        .getQueryData<Task[]>(channelFeedQueryKey("dest"))
        ?.map((task) => [task.id, task.channel]),
    ).toEqual([
      ["t2", "dest"],
      ["t1", "dest"],
    ]);
    await act(async () => {
      resolveFile?.({ taskId: "t1", channelId: "dest", createdAt: 4 });
      await filing;
    });

    expect(queryClient.getQueryData(listKey("dest"))).toEqual([
      { channelId: "dest", taskId: "t2", createdAt: 2 },
      { channelId: "dest", taskId: "t1", createdAt: 4 },
    ]);
  });

  it("restores cached channels when filing fails", async () => {
    let rejectFile: ((error: Error) => void) | null = null;
    mutations.file.mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectFile = reject;
        }),
    );
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });
    let filing: Promise<unknown>;

    await act(async () => {
      filing = result.current.fileTask("dest", "t1");
      await Promise.resolve();
    });

    expect(queryClient.getQueryData(listKey("source"))).toEqual([]);
    queryClient.setQueryData(listKey("unrelated"), [
      { channelId: "unrelated", taskId: "t3", createdAt: 3 },
      { channelId: "unrelated", taskId: "t4", createdAt: 4 },
    ]);

    await act(async () => {
      rejectFile?.(new Error("Request failed"));
      await filing.catch(() => undefined);
    });

    expect(queryClient.getQueryData(listKey("source"))).toEqual([
      { channelId: "source", taskId: "t1", createdAt: 1 },
    ]);
    expect(queryClient.getQueryData(listKey("dest"))).toEqual([
      { channelId: "dest", taskId: "t2", createdAt: 2 },
    ]);
    expect(queryClient.getQueryData(listKey("unrelated"))).toEqual([
      { channelId: "unrelated", taskId: "t3", createdAt: 3 },
      { channelId: "unrelated", taskId: "t4", createdAt: 4 },
    ]);
    expect(queryClient.getQueryData<Task>(taskKeys.detail("t1"))?.channel).toBe(
      "source",
    );
    expect(
      queryClient.getQueryData<Task[]>(taskKeys.list())?.[0]?.channel,
    ).toBe("source");
    expect(
      queryClient
        .getQueryData<Task[]>(channelFeedQueryKey("source"))
        ?.map((task) => [task.id, task.channel]),
    ).toEqual([["t1", "source"]]);
    expect(
      queryClient
        .getQueryData<Task[]>(channelFeedQueryKey("dest"))
        ?.map((task) => [task.id, task.channel]),
    ).toEqual([["t2", "dest"]]);
  });

  it("does not roll back a newer filing of the same task", async () => {
    const firstRequest = deferred<{
      taskId: string;
      channelId: string;
      createdAt: number;
    }>();
    const secondRequest = deferred<{
      taskId: string;
      channelId: string;
      createdAt: number;
    }>();
    mutations.file
      .mockImplementationOnce(() => firstRequest.promise)
      .mockImplementationOnce(() => secondRequest.promise);
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });

    let firstFiling = Promise.resolve<unknown>(undefined);
    let secondFiling = Promise.resolve<unknown>(undefined);
    await act(async () => {
      firstFiling = result.current.fileTask("dest", "t1");
      await Promise.resolve();
      secondFiling = result.current.fileTask("dest", "t1");
      await Promise.resolve();
    });

    await act(async () => {
      firstRequest.reject(new Error("First request failed"));
      await firstFiling.catch(() => undefined);
    });

    expect(
      queryClient
        .getQueryData<{ taskId: string }[]>(listKey("dest"))
        ?.map((record) => record.taskId),
    ).toEqual(["t2", "t1"]);

    await act(async () => {
      secondRequest.resolve({ taskId: "t1", channelId: "dest", createdAt: 5 });
      await secondFiling;
    });
  });

  it("marks a new optimistic destination query as auth scoped", async () => {
    queryClient.removeQueries({ queryKey: listKey("new-dest"), exact: true });
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });

    await act(async () => {
      await result.current.fileTask("new-dest", "t1");
    });

    expect(
      queryClient.getQueryCache().find({
        queryKey: listKey("new-dest"),
        exact: true,
      })?.meta,
    ).toMatchObject(AUTH_SCOPED_QUERY_META);
  });

  it("filing a task invalidates a channel whose list is still loading", async () => {
    // A first load has no cached membership to check, and its request may have
    // gone out before the mutation. Skipping it lets the pre-mutation response
    // land and sit fresh, leaving the task showing in the space it left.
    queryClient
      .getQueryCache()
      .build(queryClient, { queryKey: listKey("loading") });
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });

    await act(async () => {
      await result.current.fileTask("dest", "t1");
    });

    expect(invalidatedChannels()).toEqual(["dest", "loading", "source"]);
  });

  it("unfiling a task invalidates only the channel that listed it", async () => {
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });

    await act(async () => {
      await result.current.unfileTask("t1");
    });

    expect(invalidatedChannels()).toEqual(["source"]);
  });
});
