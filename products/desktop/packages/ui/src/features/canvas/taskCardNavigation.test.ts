import { describe, expect, it } from "vitest";
import { taskCardNavigation } from "./taskCardNavigation";

describe("taskCardNavigation", () => {
  it("opens the channel task view", () => {
    expect(taskCardNavigation("channel-1", "task-1")).toEqual({
      to: "/website/$channelId/tasks/$taskId",
      params: { channelId: "channel-1", taskId: "task-1" },
    });
  });
});
