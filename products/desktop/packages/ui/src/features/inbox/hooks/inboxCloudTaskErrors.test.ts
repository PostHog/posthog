import { describe, expect, it } from "vitest";
import { isSignalReportTaskCapError } from "./inboxCloudTaskErrors";

describe("isSignalReportTaskCapError", () => {
  it("recognizes the task cap in the serialized API error", () => {
    expect(
      isSignalReportTaskCapError(
        'Failed request: [429] {"type":"rate_limit","code":"signal_report_task_cap","error":"A PR task already exists"}',
      ),
    ).toBe(true);
  });

  it("does not treat other rate limits as the report task cap", () => {
    expect(
      isSignalReportTaskCapError(
        'Failed request: [429] {"type":"rate_limit","code":"throttled"}',
      ),
    ).toBe(false);
  });
});
