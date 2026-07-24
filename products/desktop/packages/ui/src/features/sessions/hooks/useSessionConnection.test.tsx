import type { Task } from "@posthog/shared/domain-types";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const unregisterMountedTask = vi.fn();
  const sessionService = {
    registerMountedTask: vi.fn(() => unregisterMountedTask),
    startActivityHeartbeat: vi.fn(() => () => {}),
    reconcileTaskConnection: vi.fn(() => () => {}),
  };
  return { sessionService, unregisterMountedTask };
});

vi.mock("@posthog/di/react", () => ({
  useService: () => mocks.sessionService,
}));

vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

vi.mock("@posthog/ui/hooks/useConnectivity", () => ({
  useConnectivity: () => ({ isOnline: true }),
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (selector: (state: Record<string, unknown>) => unknown) =>
    selector({
      status: "unauthenticated",
      bootstrapComplete: false,
      currentProjectId: null,
      cloudRegion: null,
    }),
}));

vi.mock("./useChatTitleGenerator", () => ({
  useChatTitleGenerator: vi.fn(),
}));

import { useSessionConnection } from "./useSessionConnection";

function makeTask(id: string): Task {
  return { id, title: id, description: id } as Task;
}

function connectionProps(taskId: string) {
  return {
    taskId,
    task: makeTask(taskId),
    session: undefined,
    repoPath: null,
    isCloud: false,
  };
}

describe("useSessionConnection mounted-task registration", () => {
  beforeEach(() => {
    mocks.sessionService.registerMountedTask.mockClear();
    mocks.unregisterMountedTask.mockClear();
  });

  it("registers the task on mount and unregisters on unmount", () => {
    const { unmount } = renderHook(() =>
      useSessionConnection(connectionProps("task-1")),
    );

    expect(mocks.sessionService.registerMountedTask).toHaveBeenCalledWith(
      "task-1",
    );
    expect(mocks.unregisterMountedTask).not.toHaveBeenCalled();

    unmount();
    expect(mocks.unregisterMountedTask).toHaveBeenCalledTimes(1);
  });

  it("re-registers when the task changes", () => {
    const { rerender, unmount } = renderHook(
      ({ taskId }: { taskId: string }) =>
        useSessionConnection(connectionProps(taskId)),
      { initialProps: { taskId: "task-1" } },
    );

    rerender({ taskId: "task-2" });

    expect(mocks.unregisterMountedTask).toHaveBeenCalledTimes(1);
    expect(mocks.sessionService.registerMountedTask).toHaveBeenLastCalledWith(
      "task-2",
    );

    unmount();
    expect(mocks.unregisterMountedTask).toHaveBeenCalledTimes(2);
  });
});
