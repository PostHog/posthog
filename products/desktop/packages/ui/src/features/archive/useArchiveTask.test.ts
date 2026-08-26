import type { Schemas } from "@posthog/api-client";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { taskKeys } from "../tasks/taskKeys";
import { getCachedArchiveTask } from "./useArchiveTask";

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
    } satisfies Schemas.TaskSummary;
    queryClient.setQueryData(taskKeys.summaries([summary.id]), [summary]);

    expect(getCachedArchiveTask(queryClient, summary.id)).toEqual(summary);
  });
});
