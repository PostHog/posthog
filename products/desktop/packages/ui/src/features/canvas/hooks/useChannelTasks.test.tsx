import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const LIST_PATH = [["channelTasks", "list"]];
const listKey = (channelId: string) => [
  ...LIST_PATH,
  { input: { channelId }, type: "query" },
];

const mutations = vi.hoisted(() => ({
  file: vi.fn().mockResolvedValue({ taskId: "t1", channelId: "dest" }),
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
      .filter((query) => query.state.isInvalidated)
      .map(
        (query) =>
          (query.queryKey[1] as { input: { channelId: string } }).input
            .channelId,
      )
      .sort();

  beforeEach(() => {
    vi.clearAllMocks();
    // `clearAllMocks` keeps implementations, so a rejection would leak onward.
    mutations.file.mockResolvedValue({ taskId: "t1", channelId: "dest" });
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    // A user who has browsed around holds a list per channel visited. Only the
    // ones a filed task actually moves between should be refetched.
    queryClient.setQueryData(listKey("source"), [{ taskId: "t1" }]);
    queryClient.setQueryData(listKey("dest"), [{ taskId: "t2" }]);
    queryClient.setQueryData(listKey("unrelated"), [{ taskId: "t3" }]);
  });

  it("filing a task invalidates only its old and new channel", async () => {
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });

    await act(async () => {
      await result.current.fileTask("dest", "t1");
    });

    expect(invalidatedChannels()).toEqual(["dest", "source"]);
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

  it("filing a task invalidates the caches that name its space", async () => {
    const taskCacheKeys = [
      ["tasks", "list", undefined],
      ["tasks", "detail", "t1"],
      ["channel-feed", "source"],
      ["space-tree-tasks", "source"],
      ["task-feed-results", "mine"],
      ["task-activity"],
    ];
    for (const queryKey of taskCacheKeys) {
      queryClient.setQueryData(queryKey, []);
    }
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });

    await act(async () => {
      await result.current.fileTask("dest", "t1");
    });

    for (const queryKey of taskCacheKeys) {
      expect(queryClient.getQueryState(queryKey)?.isInvalidated).toBe(true);
    }
  });

  it("filing a selection invalidates once, not once per task", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });

    await act(async () => {
      await result.current.fileTasks("dest", ["t1", "t2", "t3"]);
    });

    expect(mutations.file).toHaveBeenCalledTimes(3);
    expect(
      invalidate.mock.calls.filter(
        ([filters]) =>
          (filters?.queryKey as string[] | undefined)?.[0] === "channel-feed",
      ),
    ).toHaveLength(1);
  });

  it("skips the invalidation pass when the whole selection failed", async () => {
    mutations.file.mockRejectedValue(new Error("nope"));
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });

    await act(async () => {
      const { failedIds } = await result.current.fileTasks("dest", ["t1"]);
      expect(failedIds).toEqual(["t1"]);
    });

    expect(invalidate).not.toHaveBeenCalled();
  });

  it("unfiling a task invalidates only the channel that listed it", async () => {
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });

    await act(async () => {
      await result.current.unfileTask("t1");
    });

    expect(invalidatedChannels()).toEqual(["source"]);
  });
});
