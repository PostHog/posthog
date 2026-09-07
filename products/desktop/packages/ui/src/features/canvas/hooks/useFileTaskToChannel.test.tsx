import { act, renderHook } from "@testing-library/react";
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

const mocks = vi.hoisted(() => ({
  activeChannelId: "source" as string | undefined,
  activeTaskId: "task-1" as string | undefined,
  channels: [
    { id: "source", name: "Source" },
    { id: "dest", name: "Destination" },
  ],
  fileTask: vi.fn(),
  navigate: vi.fn(),
  pathname: "/spaces/source/tasks/task-1",
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelTasks", () => ({
  useChannelTaskMutations: () => ({ fileTask: mocks.fileTask }),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: mocks.channels }),
}));

vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: mocks.toastError, success: mocks.toastSuccess },
}));

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => mocks.navigate,
  useParams: ({ select }: { select: (params: unknown) => unknown }) =>
    select({
      channelId: mocks.activeChannelId,
      taskId: mocks.activeTaskId,
    }),
  useRouter: () => ({
    state: {
      location: {
        get pathname() {
          return mocks.pathname;
        },
      },
    },
  }),
}));

import { useFileTaskToChannel } from "./useFileTaskToChannel";

describe("useFileTaskToChannel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.activeChannelId = "source";
    mocks.activeTaskId = "task-1";
    mocks.pathname = "/spaces/source/tasks/task-1";
    mocks.navigate.mockImplementation(
      ({ to, params }: { to: string; params: Record<string, string> }) => {
        mocks.pathname = to
          .replace("$channelId", params.channelId ?? "")
          .replace("$taskId", params.taskId);
        return Promise.resolve();
      },
    );
  });

  it("moves the active task route before filing completes", async () => {
    let resolveFile: (() => void) | null = null;
    mocks.fileTask.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          resolveFile = resolve;
        }),
    );
    const { result } = renderHook(() => useFileTaskToChannel());
    let filing = Promise.resolve();

    act(() => {
      filing = result.current("dest", "task-1", "Move this task");
    });

    expect(mocks.navigate).toHaveBeenCalledWith({
      to: "/spaces/$channelId/tasks/$taskId",
      params: { channelId: "dest", taskId: "task-1" },
      replace: true,
    });

    await act(async () => {
      resolveFile?.();
      await filing;
    });
  });

  it("restores the source after a pending route move completes", async () => {
    const fileRequest = deferred<void>();
    const routeMove = deferred<void>();
    mocks.fileTask.mockImplementationOnce(() => fileRequest.promise);
    mocks.navigate.mockImplementationOnce(() =>
      routeMove.promise.then(() => {
        mocks.pathname = "/spaces/dest/tasks/task-1";
      }),
    );
    const { result } = renderHook(() => useFileTaskToChannel());

    let filing = Promise.resolve();
    act(() => {
      filing = result.current("dest", "task-1", "Move this task");
    });

    fileRequest.reject(new Error("Request failed"));
    await Promise.resolve();
    expect(mocks.navigate).toHaveBeenCalledTimes(1);

    await act(async () => {
      routeMove.resolve();
      await filing;
    });

    expect(mocks.navigate).toHaveBeenLastCalledWith({
      to: "/spaces/$channelId/tasks/$taskId",
      params: { channelId: "source", taskId: "task-1" },
      replace: true,
    });
  });

  it("does not roll back a newer filing of the same task", async () => {
    const firstRequest = deferred<void>();
    const secondRequest = deferred<void>();
    mocks.fileTask
      .mockImplementationOnce(() => firstRequest.promise)
      .mockImplementationOnce(() => secondRequest.promise);
    const { result } = renderHook(() => useFileTaskToChannel());

    let firstFiling = Promise.resolve();
    let secondFiling = Promise.resolve();
    act(() => {
      firstFiling = result.current("dest", "task-1", "Move this task");
      secondFiling = result.current("dest", "task-1", "Move this task");
    });

    await act(async () => {
      firstRequest.reject(new Error("First request failed"));
      await firstFiling;
    });

    expect(mocks.navigate).toHaveBeenCalledTimes(2);
    expect(mocks.pathname).toBe("/spaces/dest/tasks/task-1");

    await act(async () => {
      secondRequest.resolve();
      await secondFiling;
    });
  });

  it.each([
    ["restores the source route", "/spaces/dest/tasks/task-1", 2],
    ["keeps a later route", "/activity", 1],
  ])("%s when filing fails", async (_label, pathBeforeFailure, callCount) => {
    let rejectFile: ((error: Error) => void) | null = null;
    mocks.fileTask.mockImplementationOnce(
      () =>
        new Promise<void>((_resolve, reject) => {
          rejectFile = reject;
        }),
    );
    const { result } = renderHook(() => useFileTaskToChannel());
    let filing = Promise.resolve();

    act(() => {
      filing = result.current("dest", "task-1", "Move this task");
    });
    mocks.pathname = pathBeforeFailure;

    await act(async () => {
      rejectFile?.(new Error("Request failed"));
      await filing;
    });

    expect(mocks.navigate).toHaveBeenCalledTimes(callCount);
    if (callCount === 2) {
      expect(mocks.navigate).toHaveBeenLastCalledWith({
        to: "/spaces/$channelId/tasks/$taskId",
        params: { channelId: "source", taskId: "task-1" },
        replace: true,
      });
    }
    expect(mocks.toastError).toHaveBeenCalledWith("Couldn't file task", {
      description: "Request failed",
    });
  });
});
