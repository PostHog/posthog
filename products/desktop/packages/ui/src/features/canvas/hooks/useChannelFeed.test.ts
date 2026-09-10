import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { filterTasksByPendingFilings } from "./useChannelFeed";

describe("filterTasksByPendingFilings", () => {
  it("removes a task from its source feed while filing is pending", () => {
    const task = { id: "task-1" } as Task;
    const filings = [
      { channelId: "destination", taskId: "task-1", submittedAt: 1 },
    ];

    expect(filterTasksByPendingFilings([task], "source", filings)).toEqual([]);
    expect(filterTasksByPendingFilings([task], "destination", filings)).toEqual(
      [task],
    );
  });
});
