import { describe, expect, it } from "vitest";
import {
  cohortCriteriaSection,
  compactCount,
  dailySparkPoints,
  decorateFlagPreview,
  decorateSurveyPreview,
  exposureFact,
  gridRows,
  hogqlEscape,
  pivotDailyGroups,
  shapeActionPreview,
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
    expect(preview).toMatchObject({
      title: "new-checkout-flow",
      detail: "New checkout rollout",
      status: { label: "Enabled", tone: "positive" },
      facts: ["25% rollout", "2 variants", "Used by 1 experiment"],
      resolvedId: "42",
    });
    expect(preview.sections).toContainEqual({
      title: "Configuration",
      fields: expect.arrayContaining([
        { label: "Type", value: "Multivariate" },
        { label: "Release conditions", value: "1 condition" },
      ]),
    });
  });

  it("summarizes flag release conditions without exposing raw filter JSON", () => {
    const preview = shapeFlagPreview({
      id: 42,
      key: "new-checkout-flow",
      active: true,
      filters: {
        groups: [
          {
            properties: [
              {
                key: "plan",
                operator: "exact",
                value: "pro",
              },
            ],
            rollout_percentage: 25,
            variant: "test",
          },
        ],
      },
    } as unknown as Schemas.FeatureFlag);

    expect(preview.sections).toContainEqual({
      title: "Release conditions",
      fields: [
        {
          label: "Set 1",
          value: "plan exact pro · 25% rollout · Variant: test",
        },
      ],
    });
  });

  it("shows a disabled flag without a name as just the state", () => {
    const preview = shapeFlagPreview({
      id: 7,
      key: "old-flag",
      active: false,
    } as Schemas.FeatureFlag);
    expect(preview.detail).toBeUndefined();
    expect(preview.status).toEqual({ label: "Disabled", tone: "neutral" });
  });

  it.each([
    ["draft", {}, "Draft", undefined],
    [
      "running",
      { start_date: "2024-01-03T10:00:00Z" },
      "Running",
      /· Started Jan 3/,
    ],
    [
      "ended",
      { start_date: "2024-01-03T10:00:00Z", end_date: "2024-02-02T10:00:00Z" },
      "Ended",
      /^Jan 3(, \d{4})? to Feb 2/,
    ],
  ] as const)(
    "describes a %s experiment",
    (_state, dates, statusLabel, detail) => {
      const preview = shapeExperimentPreview({
        id: 7,
        name: "Reminder timing",
        ...dates,
      } as Schemas.Experiment);
      expect(preview.title).toBe("Reminder timing");
      expect(preview.status?.label).toBe(statusLabel);
      if (detail) {
        expect(preview.detail).toMatch(detail);
      } else {
        expect(preview.detail).toBeUndefined();
      }
    },
  );

  it.each([
    ["paused", "Paused", "caution"],
    ["exposure_frozen", "Exposure frozen", "neutral"],
  ] as const)(
    "labels a %s experiment from the API status, not the start date",
    (apiStatus, label, tone) => {
      const preview = shapeExperimentPreview({
        id: 7,
        name: "Reminder timing",
        start_date: "2024-01-03T10:00:00Z",
        status: apiStatus,
      } as unknown as Schemas.Experiment);
      expect(preview.status).toEqual({ label, tone });
    },
  );

  it("humanizes the error issue status", () => {
    const preview = shapeErrorIssuePreview({
      id: "018f",
      name: "TypeError in CouponValidator",
      status: "pending_release",
      first_seen: "2024-01-03T10:00:00Z",
    } as Schemas.ErrorTrackingIssueFull);
    expect(preview.detail).toMatch(/^First seen Jan 3/);
    expect(preview.status).toEqual({
      label: "Pending release",
      tone: "neutral",
    });
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
    ).toMatchObject({
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

  it("exposes chartable tiles by insight short id, skipping tiles without one", () => {
    const preview = shapeDashboardPreview({
      id: 12,
      name: "Growth",
      tiles: [
        { insight: { name: "DAU", short_id: "abc123" } },
        { insight: { name: "Text tile without insight id" } },
        { text: { body: "A text tile" } },
      ],
    } as unknown as Schemas.Dashboard);
    expect(preview.tiles).toEqual([{ shortId: "abc123", name: "DAU" }]);
  });

  it("caps chartable tiles so a large dashboard doesn't open one query per tile", () => {
    const tiles = Array.from({ length: 20 }, (_, index) => ({
      insight: { name: `Insight ${index}`, short_id: `id${index}` },
    }));
    const preview = shapeDashboardPreview({
      id: 12,
      name: "Growth",
      tiles,
    } as unknown as Schemas.Dashboard);
    expect(preview.tiles).toHaveLength(6);
    expect(preview.tiles?.[0]).toEqual({ shortId: "id0", name: "Insight 0" });
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

  it("describes cohort membership criteria as prose, skipping unknown nodes", () => {
    const sections = cohortCriteriaSection({
      properties: {
        type: "OR",
        values: [
          {
            type: "AND",
            values: [
              {
                type: "behavioral",
                value: "performed_event",
                key: "$pageview",
                time_value: 30,
                time_interval: "day",
              },
              {
                type: "person",
                key: "email",
                operator: "icontains",
                value: "@example.com",
              },
            ],
          },
          {
            type: "OR",
            values: [
              { type: "mystery", key: "??" },
              {
                type: "behavioral",
                value: "performed_event_multiple",
                key: "file saved",
                operator: "gte",
                operator_value: 3,
                time_value: 1,
                time_interval: "week",
              },
            ],
          },
        ],
      },
    });
    expect(sections).toEqual([
      {
        title: "Membership criteria",
        fields: [
          {
            label: "Group 1",
            value:
              "Completed $pageview in the last 30 days and email contains @example.com",
          },
          {
            label: "Group 2 (or)",
            value: "Completed file saved at least 3 times in the last 1 week",
          },
        ],
      },
    ]);
  });

  it("renders negated criteria as their negative meaning", () => {
    const sections = cohortCriteriaSection({
      properties: {
        type: "AND",
        values: [
          {
            type: "AND",
            values: [
              {
                type: "behavioral",
                value: "performed_event",
                key: "checkout",
                negation: true,
              },
              {
                type: "cohort",
                value: "Power users",
                negation: true,
              },
              {
                type: "person",
                key: "email",
                operator: "icontains",
                value: "@example.com",
                negation: true,
              },
            ],
          },
        ],
      },
    });
    expect(sections).toEqual([
      {
        title: "Membership criteria",
        fields: [
          {
            label: "Criteria",
            value:
              "Did not complete checkout and Is not in cohort Power users and email does not contain @example.com",
          },
        ],
      },
    ]);
  });

  it("renders the legacy multiple-event alias with its count rule", () => {
    const sections = cohortCriteriaSection({
      properties: {
        type: "AND",
        values: [
          {
            type: "AND",
            values: [
              {
                type: "behavioral",
                value: "performed_event_multiple_times",
                key: "$pageview",
                operator: "gte",
                operator_value: 5,
                time_value: 30,
                time_interval: "day",
              },
            ],
          },
        ],
      },
    });
    expect(sections[0]?.fields[0]?.value).toBe(
      "Completed $pageview at least 5 times in the last 30 days",
    );
  });

  it("returns no criteria section for a static or malformed cohort", () => {
    expect(cohortCriteriaSection(undefined)).toEqual([]);
    expect(cohortCriteriaSection({ properties: { values: "junk" } })).toEqual(
      [],
    );
  });

  it("pivots (day, group, count) rows into zero-filled series per group", () => {
    expect(
      pivotDailyGroups([
        ["2026-08-02", "control", 4],
        ["2026-08-01", "control", 2],
        ["2026-08-01", "test", 3],
      ]),
    ).toEqual({
      labels: ["2026-08-01", "2026-08-02"],
      series: [
        { label: "control", data: [2, 4] },
        { label: "test", data: [3, 0] },
      ],
      omittedGroups: 0,
    });
    expect(pivotDailyGroups([["2026-08-01", "control", 2]])).toBeNull();
  });

  it("keeps the highest-volume groups and counts the omitted ones", () => {
    // 7 variants over 2 days; "control" has the largest total but appears last
    // in row order, so first-seen slicing would have dropped it.
    const variants: Array<[string, number]> = [
      ["a", 1],
      ["b", 2],
      ["c", 3],
      ["d", 4],
      ["e", 5],
      ["f", 6],
      ["control", 100],
    ];
    const rows = ["2026-08-01", "2026-08-02"].flatMap((day) =>
      variants.map(([variant, count]) => [day, variant, count]),
    );
    const pivot = pivotDailyGroups(rows);
    expect(pivot?.omittedGroups).toBe(1);
    expect(pivot?.series.map((entry) => entry.label)).toEqual([
      "control",
      "f",
      "e",
      "d",
      "c",
      "b",
    ]);
  });

  it("describes action match groups in its details", () => {
    const preview = shapeActionPreview({
      id: 42,
      name: "Checkout click",
      description: "Tracks checkout clicks",
      steps: [
        {
          event: "$autocapture",
          url: "/checkout",
          selector: "button[data-attr=checkout]",
          properties: [{ key: "$current_url", value: "/checkout" }],
        },
      ],
      is_calculating: false,
      last_calculated_at: "2024-01-03T10:00:00Z",
      created_at: "2024-01-02T10:00:00Z",
    } as unknown as Schemas.Action);

    expect(preview.sections).toContainEqual({
      title: "Match groups",
      fields: [
        {
          label: "Group 1",
          value:
            "Event: $autocapture · URL: /checkout · Selector: button[data-attr=checkout] · 1 property",
        },
      ],
    });
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
      labels: ["2024-01-01", "2024-01-02"],
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
    ).toMatchObject({
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
    expect(preview.detail).toMatch(/^Day 12 ·/);
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
    expect(preview).toMatchObject({
      title: "Checkout survey",
      status: { label: "Draft", tone: "neutral" },
    });
  });
});
