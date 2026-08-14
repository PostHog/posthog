import { describe, expect, it } from "vitest";
import {
  shapeCohortPreview,
  shapeErrorIssuePreview,
  shapeExperimentPreview,
  shapeFlagPreview,
  shapeHogqlPreview,
  shapeInsightPreview,
  shapeRecordingPreview,
  shapeSurveyPreview,
} from "./evidence-previews";
import type { Schemas } from "./generated";

// The shapers only read the fields they show; build minimal inputs and cast.
function insight(fields: Partial<Schemas.Insight>): Schemas.Insight {
  return { short_id: "9pQx3", ...fields } as Schemas.Insight;
}

describe("evidence preview shaping", () => {
  it.each([
    ["name", insight({ name: "Checkout funnel" }), "Checkout funnel"],
    [
      "derived name",
      insight({ name: null, derived_name: "Pageview trend" }),
      "Pageview trend",
    ],
    ["short id", insight({ name: null, derived_name: null }), "9pQx3"],
  ])("falls back to the insight %s for the title", (_case, input, title) => {
    expect(shapeInsightPreview(input).title).toBe(title);
  });

  it("keys the flag preview by key and carries the numeric id for links", () => {
    const preview = shapeFlagPreview({
      id: 42,
      key: "new-checkout-flow",
      name: "New checkout rollout",
      active: true,
    } as Schemas.FeatureFlag);
    expect(preview).toEqual({
      title: "new-checkout-flow",
      detail: "Enabled · New checkout rollout",
      resolvedId: "42",
    });
  });

  it("shows a disabled flag without a name as just the state", () => {
    const preview = shapeFlagPreview({
      id: 7,
      key: "old-flag",
      active: false,
    } as Schemas.FeatureFlag);
    expect(preview.detail).toBe("Disabled");
  });

  it.each([
    ["draft", {}, "Draft"],
    ["running", { start_date: "2024-01-03T10:00:00Z" }, /^Running since Jan 3/],
    [
      "ended",
      { start_date: "2024-01-03T10:00:00Z", end_date: "2024-02-02T10:00:00Z" },
      /^Ended Feb 2/,
    ],
  ])("describes a %s experiment", (_state, dates, expected) => {
    const preview = shapeExperimentPreview({
      id: 7,
      name: "Reminder timing",
      ...dates,
    } as Schemas.Experiment);
    expect(preview.title).toBe("Reminder timing");
    if (typeof expected === "string") {
      expect(preview.detail).toBe(expected);
    } else {
      expect(preview.detail).toMatch(expected);
    }
  });

  it("humanizes the error issue status", () => {
    const preview = shapeErrorIssuePreview({
      id: "018f",
      name: "TypeError in CouponValidator",
      status: "pending_release",
      first_seen: "2024-01-03T10:00:00Z",
    } as Schemas.ErrorTrackingIssueFull);
    expect(preview.detail).toMatch(/^Pending release · First seen Jan 3/);
  });

  it.each([
    ["minutes", 754, /^13 min/],
    ["seconds", 42, /^42s/],
  ])("formats the recording duration in %s", (_unit, seconds, expected) => {
    const preview = shapeRecordingPreview({
      id: "s_1",
      distinct_id: "user-1",
      recording_duration: seconds,
      start_time: "2024-01-03T10:00:00Z",
    } as Schemas.SessionRecording);
    expect(preview.title).toBe("Session by user-1");
    expect(preview.detail).toMatch(expected);
  });

  it("describes a cohort by its size, falling back to the description", () => {
    expect(
      shapeCohortPreview({
        id: 31,
        name: "Power users",
        count: 1247,
      } as Schemas.Cohort).detail,
    ).toBe("1,247 people");
    expect(
      shapeCohortPreview({
        id: 31,
        name: "Power users",
        count: null,
        description: "Weekly active users",
      } as Schemas.Cohort).detail,
    ).toBe("Weekly active users");
  });

  it.each([
    [
      "a single numeric cell as the value",
      { results: [[17100]], columns: ["count"] },
      { title: "17,100", detail: "count" },
    ],
    [
      "a grid as a row count with its columns",
      {
        results: [
          [1, 2],
          [3, 4],
        ],
        columns: ["day", "users"],
      },
      { title: "2 rows", detail: "day, users" },
    ],
  ])("summarizes a hogql result: %s", (_case, response, expected) => {
    expect(shapeHogqlPreview(response)).toEqual(expected);
  });

  it("describes a survey that has not started as a draft", () => {
    const preview = shapeSurveyPreview({
      id: "srv-11",
      name: "Checkout survey",
    } as Schemas.Survey);
    expect(preview).toEqual({ title: "Checkout survey", detail: "Draft" });
  });
});
