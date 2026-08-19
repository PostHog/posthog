import { describe, expect, it } from "vitest";
import {
  compactCount,
  dailySparkPoints,
  decorateFlagPreview,
  decorateSurveyPreview,
  exposureFact,
  gridRows,
  hogqlEscape,
  shapeCohortPreview,
  shapeDashboardPreview,
  shapeErrorIssuePreview,
  shapeEvaluationPreview,
  shapeEventDefinitionPreview,
  shapeExperimentPreview,
  shapeFlagPreview,
  shapePersonPreview,
  shapeRecordingPreview,
  shapeSurveyPreview,
  shapeTicketPreview,
  shapeTracePreview,
} from "./evidence-previews";
import type { Schemas } from "./generated";

// The shapers only read the fields they show; build minimal inputs and cast.
describe("evidence preview shaping", () => {
  it("keys the flag preview by key and carries the numeric id for links", () => {
    const preview = shapeFlagPreview({
      id: 42,
      key: "new-checkout-flow",
      name: "New checkout rollout",
      active: true,
      filters: {
        groups: [{ rollout_percentage: 25 }],
        multivariate: { variants: [{ key: "a" }, { key: "b" }] },
      },
      experiment_set: [7],
    } as unknown as Schemas.FeatureFlag);
    expect(preview).toEqual({
      title: "new-checkout-flow",
      detail: "Enabled · New checkout rollout",
      facts: ["25% rollout", "2 variants", "Used by 1 experiment"],
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

  it("surfaces a recording's activity and entry page as facts", () => {
    const preview = shapeRecordingPreview({
      id: "s_1",
      distinct_id: "user-1",
      recording_duration: 120,
      click_count: 42,
      console_error_count: 3,
      start_url: "https://app.example.com/checkout?step=2",
    } as Schemas.SessionRecording);
    expect(preview.facts).toEqual([
      "42 clicks",
      "3 console errors",
      "app.example.com/checkout",
    ]);
  });

  it("describes an evaluation with its state, reason, and type", () => {
    expect(
      shapeEvaluationPreview({
        id: "ev1",
        name: "Faithfulness eval",
        enabled: true,
        status: "degraded",
        status_reason: "Provider key expired",
        evaluation_type: "llm_judge",
      } as unknown as Schemas.Evaluation),
    ).toEqual({
      title: "Faithfulness eval",
      detail: "Enabled · Provider key expired",
      facts: ["LLM judge"],
    });
  });

  it("names a dashboard's tiles instead of counting them", () => {
    const preview = shapeDashboardPreview({
      id: 12,
      name: "Growth",
      tiles: [
        { insight: { name: "DAU" } },
        { insight: { name: "Signup funnel" } },
        { insight: { name: "Revenue" } },
        { insight: { name: "Churn" } },
      ],
    } as unknown as Schemas.Dashboard);
    expect(preview.facts).toEqual([
      "DAU",
      "Signup funnel",
      "Revenue",
      "+1 more",
    ]);
  });

  // The remainder counts unnamed tiles too: named tiles are shown, but every
  // tile that filtered out of the name list still has to appear in "+N more".
  it.each([
    [
      [{ insight: { name: "DAU" } }, {}, {}],
      ["DAU", "+2 more"],
    ],
    [
      [
        { insight: { name: "DAU" } },
        { insight: { name: "Revenue" } },
        {},
        {},
        {},
      ],
      ["DAU", "Revenue", "+3 more"],
    ],
  ])("counts unnamed tiles in the remainder", (tiles, expected) => {
    const preview = shapeDashboardPreview({
      id: 12,
      name: "Growth",
      tiles,
    } as unknown as Schemas.Dashboard);
    expect(preview.facts).toEqual(expected);
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

  it("summarizes a ticket with its snippet, state line, and traffic", () => {
    const preview = shapeTicketPreview({
      id: "t1",
      ticket_number: 841,
      email_subject: "Coupon code rejected at checkout",
      status: "on_hold",
      priority: "high",
      channel_source: "email",
      message_count: 12,
      last_message_at: "2024-01-03T10:00:00Z",
      last_message_text: "Still failing after clearing cookies",
      assignee: { id: "u1", type: "user", user: { first_name: "Ann" } },
    } as unknown as Schemas.Ticket);
    expect(preview.title).toBe("Coupon code rejected at checkout");
    expect(preview.detail).toBe("“Still failing after clearing cookies”");
    expect(preview.facts).toEqual([
      "On hold · High · Email",
      "12 messages · last reply Jan 3, 2024",
      "Assigned to Ann",
    ]);
  });

  it("falls back to the ticket number when there is no subject", () => {
    const preview = shapeTicketPreview({
      id: "t1",
      ticket_number: 841,
      channel_source: "widget",
    } as unknown as Schemas.Ticket);
    expect(preview.title).toBe("Ticket #841");
  });

  it("identifies a person by name or email and carries the uuid for links", () => {
    expect(
      shapePersonPreview({
        id: 1,
        name: "",
        uuid: "0192-aaaa",
        distinct_ids: ["d1"],
        properties: { email: "ann@example.com" },
        created_at: "2024-03-01T00:00:00Z",
        last_seen_at: "2024-01-03T10:00:00Z",
      } as unknown as Schemas.PersonRecord),
    ).toMatchObject({
      title: "ann@example.com",
      detail: expect.stringMatching(/^Last seen Jan 3/),
      resolvedId: "0192-aaaa",
    });
  });

  it("adds a person's country and browser as pills", () => {
    const preview = shapePersonPreview({
      id: 1,
      name: "Ann",
      uuid: "u1",
      distinct_ids: ["d1"],
      properties: { $geoip_country_name: "Germany", $browser: "Chrome" },
      created_at: "2024-03-01T00:00:00Z",
    } as unknown as Schemas.PersonRecord);
    expect(preview.facts).toEqual(["Germany", "Chrome"]);
  });

  it("verifies an event by its definition and resolves the page id", () => {
    expect(
      shapeEventDefinitionPreview({
        id: "def-1",
        name: "cart_saved",
        last_seen_at: "2024-01-03T10:00:00Z",
      } as unknown as Schemas.EventDefinitionRecord),
    ).toMatchObject({
      title: "cart_saved",
      detail: expect.stringMatching(/^Last seen Jan 3/),
      resolvedId: "def-1",
    });
  });

  it.each([
    ["quotes", "it's", "it\\'s"],
    ["backslashes", "a\\b", "a\\\\b"],
  ])("escapes %s for hogql interpolation", (_name, input, expected) => {
    expect(hogqlEscape(input)).toBe(expected);
  });

  it("reduces a daily grid to spark points and compact totals", () => {
    const rows = gridRows({
      results: [
        ["2024-01-01", 5100000],
        ["2024-01-02", 4900000],
      ],
    });
    expect(dailySparkPoints(rows)).toEqual([5100000, 4900000]);
    expect(compactCount(10000000)).toBe("10M");
  });

  // Guards the rounding boundary: the unit is picked after the mantissa
  // rounds, so a value that rounds to 1000 of the lower unit promotes.
  it.each([
    [999499, "999K"],
    [999500, "1M"],
    [999999, "1M"],
    [-999999, "-1M"],
    [999499999, "999M"],
    [999500000, "1B"],
    [999999999, "1B"],
  ])("formats %d as %s without a four-digit mantissa", (input, expected) => {
    expect(compactCount(input)).toBe(expected);
  });

  it("leads a stale flag with the verdict and PostHog's reason", () => {
    const preview = decorateFlagPreview(
      {
        title: "old-flag",
        detail: "Enabled · Old rollout",
        facts: ["100% rollout"],
      },
      { status: "stale", reason: "Rolled out to 100% for at least 30 days" },
      [
        ["2024-01-01", 900000],
        ["2024-01-02", 1200000],
      ],
    );
    expect(preview.detail).toBe("Rolled out to 100% for at least 30 days");
    expect(preview.facts).toEqual(["Stale", "100% rollout", "2.1M calls (7d)"]);
    expect(preview.spark).toEqual({
      points: [900000, 1200000],
      render: "line",
    });
  });

  it("summarizes variant exposures, dropping boolean noise", () => {
    expect(
      exposureFact([
        ["control", 12400],
        ["test", 12100],
        ["false", 900],
      ]),
    ).toBe("control 12.4K · test 12.1K");
    expect(exposureFact([])).toBeNull();
  });

  it("rolls a trace up to generations, cost, latency, and errors", () => {
    expect(
      shapeTracePreview([7, 0.42, 18.3, ["gpt-5", "claude-4"], 2]),
    ).toEqual({
      title: "7 generations",
      facts: ["$0.42", "18.3s", "2 models", "2 errors"],
    });
    expect(shapeTracePreview([0, 0, 0, [], 0])).toBeNull();
  });

  it("adds responses and response rate from survey stats", () => {
    const preview = decorateSurveyPreview(
      { title: "Checkout survey", detail: "Running since Jan 3" },
      {
        stats: { "survey sent": { total_count: 128 } },
        rates: { response_rate: 34.4 },
      },
    );
    expect(preview.facts).toEqual(["128 responses", "34% response rate"]);
  });

  it("describes a running experiment with its day counter and split", () => {
    const start = new Date(Date.now() - 11.5 * 86_400_000).toISOString();
    const preview = shapeExperimentPreview({
      id: 7,
      name: "Reminder timing",
      start_date: start,
      feature_flag_key: "reminder-timing",
      parameters: {
        feature_flag_variants: [
          { key: "control", rollout_percentage: 50 },
          { key: "test", rollout_percentage: 50 },
        ],
      },
    } as unknown as Schemas.Experiment);
    expect(preview.detail).toMatch(/· Day 12$/);
    expect(preview.facts).toEqual([
      "2 variants (50/50)",
      "Flag: reminder-timing",
    ]);
  });

  it("describes a survey that has not started as a draft", () => {
    const preview = shapeSurveyPreview({
      id: "srv-11",
      name: "Checkout survey",
    } as Schemas.Survey);
    expect(preview).toEqual({ title: "Checkout survey", detail: "Draft" });
  });
});
