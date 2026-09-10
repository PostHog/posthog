import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

interface FilingResult {
  taskId: string;
  channelId: string;
  createdAt: number;
}

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
const FILE_KEY = [["channelTasks", "file"]];
const listKey = (channelId: string) => [
  ...LIST_PATH,
  { input: { channelId }, type: "query" },
];

const mocks = vi.hoisted(() => ({
  file: vi.fn(),
  rows: {} as Record<string, FilingResult[]>,
  unfile: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    channelTasks: {
      list: {
        mutationKey: () => FILE_KEY,
        pathFilter: () => ({ queryKey: LIST_PATH }),
        queryOptions: (
          { channelId }: { channelId: string },
          options: object,
        ) => ({
          ...options,
          queryKey: listKey(channelId),
          queryFn: async () => mocks.rows[channelId] ?? [],
        }),
      },
      file: {
        mutationKey: () => FILE_KEY,
        mutationOptions: (options: object) => ({
          ...options,
          mutationKey: FILE_KEY,
          mutationFn: mocks.file,
        }),
      },
      unfile: {
        mutationOptions: (options: object) => ({
          ...options,
          mutationFn: mocks.unfile,
        }),
      },
    },
  }),
}));

import {
  applyPendingTaskFilings,
  useChannelTaskMutations,
  useChannelTasks,
} from "./useChannelTasks";

describe("useChannelTasks", () => {
  let queryClient: QueryClient;

  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  function useFilingHarness() {
    return {
      source: useChannelTasks("source"),
      destination: useChannelTasks("dest"),
      third: useChannelTasks("third"),
      mutations: useChannelTaskMutations(),
    };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mocks.rows = {
      source: [{ channelId: "source", taskId: "t1", createdAt: 1 }],
      dest: [{ channelId: "dest", taskId: "t2", createdAt: 2 }],
      third: [],
    };
    for (const [channelId, rows] of Object.entries(mocks.rows)) {
      queryClient.setQueryData(listKey(channelId), rows);
    }
  });

  it("moves a task between visible channels while filing is pending", async () => {
    const request = deferred<FilingResult>();
    mocks.file.mockReturnValueOnce(request.promise);
    const { result } = renderHook(useFilingHarness, { wrapper });
    let filing = Promise.resolve<unknown>(undefined);

    act(() => {
      filing = result.current.mutations.fileTask("dest", "t1");
    });

    await waitFor(() => {
      expect(result.current.source.tasks).toEqual([]);
      expect(
        result.current.destination.tasks.map((task) => task.taskId),
      ).toEqual(["t2", "t1"]);
    });

    mocks.rows.source = [];
    mocks.rows.dest = [
      { channelId: "dest", taskId: "t2", createdAt: 2 },
      { channelId: "dest", taskId: "t1", createdAt: 1 },
    ];
    await act(async () => {
      request.resolve({ channelId: "dest", taskId: "t1", createdAt: 1 });
      await filing;
    });

    expect(result.current.source.tasks).toEqual([]);
    expect(result.current.destination.tasks.map((task) => task.taskId)).toEqual(
      ["t2", "t1"],
    );
  });

  it("shows the server-backed channels again when filing fails", async () => {
    const request = deferred<FilingResult>();
    mocks.file.mockReturnValueOnce(request.promise);
    const { result } = renderHook(useFilingHarness, { wrapper });
    let filing = Promise.resolve<unknown>(undefined);

    act(() => {
      filing = result.current.mutations.fileTask("dest", "t1");
    });
    await waitFor(() => expect(result.current.source.tasks).toEqual([]));

    await act(async () => {
      request.reject(new Error("Request failed"));
      await filing.catch(() => undefined);
    });

    await waitFor(() => {
      expect(result.current.source.tasks.map((task) => task.taskId)).toEqual([
        "t1",
      ]);
      expect(
        result.current.destination.tasks.map((task) => task.taskId),
      ).toEqual(["t2"]);
    });
  });

  it("sends overlapping filings of one task in order", async () => {
    const firstRequest = deferred<FilingResult>();
    const secondRequest = deferred<FilingResult>();
    mocks.file
      .mockReturnValueOnce(firstRequest.promise)
      .mockReturnValueOnce(secondRequest.promise);
    const filedChannels = (): string[] =>
      mocks.file.mock.calls.map(
        (call) => (call[0] as { channelId: string }).channelId,
      );
    const { result } = renderHook(useFilingHarness, { wrapper });
    let firstFiling = Promise.resolve<unknown>(undefined);
    let secondFiling = Promise.resolve<unknown>(undefined);

    act(() => {
      firstFiling = result.current.mutations.fileTask("dest", "t1");
      secondFiling = result.current.mutations.fileTask("third", "t1");
    });

    await waitFor(() => expect(filedChannels()).toEqual(["dest"]));

    await act(async () => {
      firstRequest.resolve({ channelId: "dest", taskId: "t1", createdAt: 1 });
      await firstFiling;
    });
    await waitFor(() => expect(filedChannels()).toEqual(["dest", "third"]));

    await act(async () => {
      secondRequest.resolve({ channelId: "third", taskId: "t1", createdAt: 1 });
      await secondFiling;
    });
  });

  it("shows a task only in its latest pending destination", () => {
    const records = [{ channelId: "source", taskId: "t1", createdAt: 1 }];
    const filings = [
      { channelId: "dest", taskId: "t1", submittedAt: 2 },
      { channelId: "third", taskId: "t1", submittedAt: 3 },
    ];

    expect(applyPendingTaskFilings(records, "source", filings)).toEqual([]);
    expect(applyPendingTaskFilings([], "dest", filings)).toEqual([]);
    expect(applyPendingTaskFilings([], "third", filings)).toEqual([
      { channelId: "third", taskId: "t1", createdAt: 3 },
    ]);
  });

  it("invalidates channel lists when unfiling succeeds", async () => {
    const { result } = renderHook(() => useChannelTaskMutations(), { wrapper });

    await act(async () => {
      await result.current.unfileTask("t1");
    });

    expect(
      queryClient
        .getQueryCache()
        .find({ queryKey: listKey("source"), exact: true })?.state
        .isInvalidated,
    ).toBe(true);
  });
});
