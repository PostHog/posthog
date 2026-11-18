import { describe, expect, it } from "vitest";
import { taskFeedRunStatus } from "./channelFeed";

describe("taskFeedRunStatus", () => {
  it("preserves a queued cloud status", () => {
    expect(
      taskFeedRunStatus({
        status: "queued",
        environment: "cloud",
      }),
    ).toBe("queued");
  });

  it.each([
    ["an active interactive run", "interactive", true, "in_progress"],
    ["an idle interactive run", "interactive", false, null],
    ["a restored background run", "background", false, "in_progress"],
  ] as const)(
    "shows the status for %s",
    (_case, runMode, isGenerating, expected) => {
      expect(
        taskFeedRunStatus({
          status: "in_progress",
          environment: "cloud",
          runMode,
          isGenerating,
        }),
      ).toBe(expected);
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
