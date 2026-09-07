import { describe, expect, it } from "vitest";
import { taskFeedRunStatus } from "./channelFeed";

describe("taskFeedRunStatus", () => {
  it.each(["queued", "in_progress"] as const)(
    "preserves a cloud %s status even when local session activity has settled",
    (status) => {
      expect(
        taskFeedRunStatus({
          status,
          environment: "cloud",
        }),
      ).toBe(status);
    },
  );

  it("hides an unreliable non-terminal local status", () => {
    expect(
      taskFeedRunStatus({ status: "queued", environment: "local" }),
    ).toBeNull();
  });

  it("keeps a terminal local status", () => {
    expect(
      taskFeedRunStatus({ status: "completed", environment: "local" }),
    ).toBe("completed");
  });
});
