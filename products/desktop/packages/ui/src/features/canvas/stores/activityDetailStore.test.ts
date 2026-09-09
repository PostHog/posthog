import { describe, expect, it } from "vitest";
import { activityReportIdFromHref } from "./activityDetailStore";

describe("activityReportIdFromHref", () => {
  it("identifies persisted Activity report tabs", () => {
    expect(
      activityReportIdFromHref("/activity?item=report-1&report=report-1"),
    ).toBe("report-1");
    expect(
      activityReportIdFromHref("/activity?item=task-1&session=session-1"),
    ).toBeNull();
  });
});
