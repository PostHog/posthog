import { describe, expect, it } from "vitest";
import { parseTaskNotificationParams } from "./schemas";

describe("parseTaskNotificationParams", () => {
  it("keeps the raw SDK payload and falls back to legacy params", () => {
    const rawPayload = {
      type: "system",
      subtype: "task_notification",
      task_id: "background-1",
      usage: { total_tokens: 120 },
    };

    expect(
      parseTaskNotificationParams({
        taskId: "background-1",
        status: "completed",
        summary: "Done",
        payload: rawPayload,
      }),
    ).toMatchObject({ payload: rawPayload });
    expect(
      parseTaskNotificationParams({
        taskId: "background-2",
        status: "failed",
        summary: "Failed",
        outputFile: "/tmp/output",
      }),
    ).toMatchObject({
      payload: {
        taskId: "background-2",
        status: "failed",
        summary: "Failed",
        outputFile: "/tmp/output",
      },
    });
  });

  it("rejects malformed notifications", () => {
    expect(
      parseTaskNotificationParams({ status: "unknown", summary: "No task" }),
    ).toBeNull();
  });
});
