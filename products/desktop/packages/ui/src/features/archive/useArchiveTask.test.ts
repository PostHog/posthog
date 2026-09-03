import type { Schemas } from "@posthog/api-client";
import type { ArchiveOrchestrationDeps } from "@posthog/core/archive/archiveOrchestration";
import { useArchivingTasksStore } from "@posthog/ui/features/sidebar/archivingTasksStore";
import { QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskKeys } from "../tasks/taskKeys";

const hoisted = vi.hoisted(() => ({
  archiveTasks: vi.fn(),
  track: vi.fn(),
}));
vi.mock(
  "@posthog/core/archive/archiveOrchestration",
  async (importOriginal) => ({
    ...(await importOriginal<object>()),
    archiveTasks: hoisted.archiveTasks,
  }),
);
// The deps factory resolves the host tRPC client up front, which a unit test
// has no container for.
vi.mock("@posthog/di/container", () => ({ resolveService: () => ({}) }));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: hoisted.track }));

import { archiveTasksImperative, getCachedArchiveTask } from "./useArchiveTask";

const keys = {
  archivedTaskIdsQueryKey: ["archived-ids"],
  archiveListQueryKey: ["archive-list"],
  archivePathFilterKey: ["archive-path-filter"],
};

beforeEach(() => {
  hoisted.archiveTasks.mockReset();
  hoisted.track.mockReset();
  useArchivingTasksStore.setState({ archivingTaskIds: new Set() });
});

// Every archive entry point — the Code sidebar, the space list, the context
// menu, and both bulk paths — builds its orchestration deps here, so wiring
// the mark to the store here is what gives all of them the in-flight state.
describe("archiveTasksImperative", () => {
  it("points the orchestration's mark at the store the rows read", async () => {
    hoisted.archiveTasks.mockImplementation(
      async (_ids: string[], deps: ArchiveOrchestrationDeps) => {
        deps.markArchiving("task-1");
        expect(useArchivingTasksStore.getState().archivingTaskIds).toContain(
          "task-1",
        );
        deps.unmarkArchiving("task-1");
        return { archived: 1, failed: 0 };
      },
    );

    await archiveTasksImperative(["task-1"], new QueryClient(), keys);

    expect(useArchivingTasksStore.getState().archivingTaskIds.size).toBe(0);
  });

  it("records how long the archive took", async () => {
    hoisted.archiveTasks.mockResolvedValue({ archived: 1, failed: 0 });

    await archiveTasksImperative(["task-1"], new QueryClient(), keys);

    expect(hoisted.track).toHaveBeenCalledWith("Task archived", {
      task_count: 1,
      task_id: "task-1",
      duration_ms: expect.any(Number),
      success: true,
    });
  });

  it("reports the failure when the archive throws", async () => {
    hoisted.archiveTasks.mockRejectedValue(new Error("host is gone"));

    await expect(
      archiveTasksImperative(["task-1"], new QueryClient(), keys),
    ).rejects.toThrow("host is gone");

    expect(hoisted.track).toHaveBeenCalledWith(
      "Task archived",
      expect.objectContaining({ success: false }),
    );
  });
});

describe("getCachedArchiveTask", () => {
  it("reads metadata from a task summary when no full list is cached", () => {
    const queryClient = new QueryClient();
    const summary = {
      id: "task-1",
      title: "Archived from sidebar",
      repository: "posthog/code",
      created_at: "2026-07-23T10:00:00.000Z",
      updated_at: "2026-07-23T11:00:00.000Z",
      latest_run: null,
    } satisfies Schemas.TaskSummaryDTO;
    queryClient.setQueryData(taskKeys.summaries([summary.id]), [summary]);

    expect(getCachedArchiveTask(queryClient, summary.id)).toEqual(summary);
  });
});
