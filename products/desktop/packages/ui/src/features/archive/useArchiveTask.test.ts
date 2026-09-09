import type { Schemas } from "@posthog/api-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useArchivingTasksStore } from "../sidebar/archivingTasksStore";
import { taskKeys } from "../tasks/taskKeys";

const mocks = vi.hoisted(() => ({
  archiveTask: vi.fn(),
}));

vi.mock(
  "@posthog/core/archive/archiveOrchestration",
  async (importOriginal) => ({
    ...(await importOriginal<
      typeof import("@posthog/core/archive/archiveOrchestration")
    >()),
    archiveTask: mocks.archiveTask,
  }),
);
vi.mock("@posthog/di/container", () => ({
  resolveService: () => ({}),
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    archive: {
      archivedTaskIds: { queryKey: () => ["archived-task-ids"] },
      list: { queryKey: () => ["archive-list"] },
      pathFilter: () => ({ queryKey: ["archive-path-filter"] }),
    },
  }),
}));
vi.mock("./useUnarchiveTask", () => ({
  useUnarchiveTask: () => ({ restore: vi.fn() }),
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: vi.fn(), dismiss: vi.fn() },
}));

import { getCachedArchiveTask, useArchiveTask } from "./useArchiveTask";

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: queryClient }, children);
}

describe("useArchiveTask", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient();
    useArchivingTasksStore.setState({
      archivingTaskIds: new Set(),
      hiddenArchivingTaskIds: new Set(),
    });
  });

  it("reads metadata from a task summary when no full list is cached", () => {
    const summary = {
      id: "task-1",
      title: "Archived from sidebar",
      repository: "posthog/code",
      created_by_id: 7,
      created_at: "2026-07-23T10:00:00.000Z",
      updated_at: "2026-07-23T11:00:00.000Z",
      latest_run: null,
    } satisfies Schemas.TaskSummaryDTO;
    queryClient.setQueryData(taskKeys.summaries([summary.id]), [summary]);

    expect(getCachedArchiveTask(queryClient, summary.id)).toEqual(summary);
  });

  it.each(["success", "failure"] as const)(
    "marks a task as archiving before slow work and clears it after %s",
    async (outcome) => {
      let settle: () => void = () => undefined;
      mocks.archiveTask.mockImplementation(
        () =>
          new Promise<void>((resolve, reject) => {
            settle = () =>
              outcome === "success" ? resolve() : reject(new Error("failed"));
          }),
      );
      const { result } = renderHook(() => useArchiveTask(), { wrapper });

      const archivePromise = result.current.archiveTask({ taskId: "task-1" });

      expect(useArchivingTasksStore.getState().isArchiving("task-1")).toBe(
        true,
      );
      expect(mocks.archiveTask).toHaveBeenCalledWith(
        "task-1",
        expect.any(Object),
        expect.objectContaining({ optimistic: false }),
      );
      settle();
      await act(async () => {
        if (outcome === "success") await archivePromise;
        else await expect(archivePromise).rejects.toThrow("failed");
      });
      expect(useArchivingTasksStore.getState().isArchiving("task-1")).toBe(
        false,
      );
    },
  );
});
