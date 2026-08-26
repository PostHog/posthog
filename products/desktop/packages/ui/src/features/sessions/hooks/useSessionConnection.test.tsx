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
  return {
    currentUser: { uuid: "user-1" } as { uuid: string } | undefined,
    sessionService,
    unregisterMountedTask,
  };
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

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({}),
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: mocks.currentUser }),
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
    mocks.currentUser = { uuid: "user-1" };
    mocks.sessionService.registerMountedTask.mockClear();
    mocks.sessionService.reconcileTaskConnection.mockClear();
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

  it.each([
    [
      "the current user is still loading",
      undefined,
      { uuid: "author" },
      undefined,
    ],
    ["the task has no author", { uuid: "user-1" }, undefined, undefined],
    [
      "the current user is the author",
      { uuid: "user-1" },
      { uuid: "user-1" },
      true,
    ],
    [
      "another user authored the task",
      { uuid: "user-1" },
      { uuid: "user-2" },
      false,
    ],
  ])("sets authorship when %s", (_case, currentUser, createdBy, expected) => {
    mocks.currentUser = currentUser;
    const props = connectionProps("task-1");
    props.task.created_by = createdBy as Task["created_by"];

    renderHook(() => useSessionConnection(props));

    expect(mocks.sessionService.reconcileTaskConnection).toHaveBeenCalledWith(
      expect.objectContaining({ isTaskAuthor: expected }),
    );
  });
});
