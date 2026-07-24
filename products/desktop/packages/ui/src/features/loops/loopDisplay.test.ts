import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  describeTrigger,
  loopFireBlockedMessage,
  loopPausedDescription,
  loopStatusColor,
  loopStatusLabel,
  nextScheduleRun,
  summarizeNotificationDestinations,
  summarizeTrigger,
} from "./loopDisplay";

const statusFields = (
  overrides: Partial<{
    enabled: boolean;
    disabled_reason: string | null;
    last_run_status: string | null;
  }> = {},
) => ({
  enabled: true,
  disabled_reason: null,
  last_run_status: null,
  ...overrides,
});

describe("loopStatusLabel and loopStatusColor", () => {
  it.each([
    [statusFields(), "Active", "green"],
    [statusFields({ last_run_status: "failed" }), "Failing", "red"],
    [statusFields({ enabled: false }), "Paused", "gray"],
    [
      statusFields({ enabled: false, disabled_reason: "usage_limited" }),
      "Paused: usage limit",
      "red",
    ],
    [
      statusFields({ enabled: false, disabled_reason: "repeated_failures" }),
      "Auto-paused",
      "red",
    ],
    [
      statusFields({ enabled: false, disabled_reason: "owner_deactivated" }),
      "Auto-paused",
      "red",
    ],
  ])("derives label and color (%#)", (loop, label, color) => {
    expect(loopStatusLabel(loop)).toBe(label);
    expect(loopStatusColor(loop)).toBe(color);
  });

  it("ignores disabled_reason while the loop is enabled", () => {
    const loop = statusFields({ disabled_reason: "usage_limited" });
    expect(loopStatusLabel(loop)).toBe("Active");
    expect(loopStatusColor(loop)).toBe("green");
  });
});

describe("loopPausedDescription", () => {
  it.each([
    ["usage_limited", "usage limit"],
    ["repeated_failures", "failed runs in a row"],
    ["owner_deactivated", "deactivated"],
    ["owner_removed_from_org", "left the organization"],
    ["github_integration_disconnected", "GitHub connection"],
  ])("explains a %s pause", (reason, expected) => {
    expect(
      loopPausedDescription(
        statusFields({ enabled: false, disabled_reason: reason }),
      ),
    ).toContain(expected);
  });

  it("falls back to a generic sentence for unknown reasons", () => {
    expect(
      loopPausedDescription(
        statusFields({ enabled: false, disabled_reason: "something_new" }),
      ),
    ).toBe("Paused automatically.");
  });

  it.each([
    [statusFields()],
    [statusFields({ enabled: false })],
    [statusFields({ disabled_reason: "usage_limited" })],
  ])("returns null without a backend-driven pause (%#)", (loop) => {
    expect(loopPausedDescription(loop)).toBeNull();
  });
});

describe("loopFireBlockedMessage", () => {
  it.each([
    ["gate_blocked", "usage limit"],
    ["overlap_skipped", "still in progress"],
    ["rate_capped", "daily run cap"],
    ["team_rate_capped", "daily loop run cap"],
    ["deduped", "already started"],
    ["disabled", "disabled"],
    ["owner_inactive", "no longer start runs"],
    ["owner_changed", "owner changed"],
  ] as const)("describes %s", (reason, expected) => {
    expect(loopFireBlockedMessage(reason)).toContain(expected);
  });
});

describe("describeTrigger", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it.each([
    ["0 * * * *", "Every hour (UTC)"],
    ["30 9 * * *", "Daily at 9:30 AM (UTC)"],
    ["0 11 * * 1-5", "Weekdays at 11:00 AM (UTC)"],
    ["15 8 * * 3", "Wednesdays at 8:15 AM (UTC)"],
  ])("formats %s as a readable schedule", (cronExpression, expected) => {
    expect(
      describeTrigger({
        type: "schedule",
        config: { cron_expression: cronExpression, timezone: "UTC" },
      }),
    ).toContain(`Schedule · ${expected} · Next run `);
  });

  it("keeps custom cron expressions visible", () => {
    expect(
      describeTrigger({
        type: "schedule",
        config: { cron_expression: "*/15 * * * *", timezone: "UTC" },
      }),
    ).toBe("Schedule · */15 * * * * (UTC)");
  });
});

describe("summarizeNotificationDestinations", () => {
  it("lists enabled destinations and includes the Slack channel", () => {
    expect(
      summarizeNotificationDestinations({
        push: { enabled: true, events: [], params: {} },
        email: { enabled: false, events: [], params: {} },
        slack: {
          enabled: true,
          events: [],
          params: { channel_name: "#loops" },
        },
      }),
    ).toEqual(["Push", "Slack · #loops"]);
  });

  it("omits disabled destinations", () => {
    expect(
      summarizeNotificationDestinations({
        push: { enabled: false, events: [], params: {} },
        email: { enabled: false, events: [], params: {} },
        slack: { enabled: false, events: [], params: {} },
      }),
    ).toEqual([]);
  });
});

describe("nextScheduleRun", () => {
  it("returns null for an invalid timezone", () => {
    expect(
      nextScheduleRun(
        { cron_expression: "0 9 * * *", timezone: "Not/A_Timezone" },
        new Date("2026-07-22T12:00:00.000Z"),
      ),
    ).toBeNull();
  });

  it("skips a local time that does not exist during DST transition", () => {
    expect(
      nextScheduleRun(
        {
          cron_expression: "30 2 * * *",
          timezone: "America/Toronto",
        },
        new Date("2026-03-08T06:00:00.000Z"),
      )?.toISOString(),
    ).toBe("2026-03-09T06:30:00.000Z");
  });

  it("finds the next weekday across a weekend", () => {
    expect(
      nextScheduleRun(
        { cron_expression: "0 9 * * 1-5", timezone: "UTC" },
        new Date("2026-07-24T10:00:00.000Z"),
      )?.toISOString(),
    ).toBe("2026-07-27T09:00:00.000Z");
  });
});

describe("summarizeTrigger", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-22T20:09:00.000Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("shows a readable schedule instead of raw cron", () => {
    expect(
      summarizeTrigger({
        type: "schedule",
        config: {
          cron_expression: "8 16 * * *",
          timezone: "America/Toronto",
        },
      }),
    ).toBe("Daily at 4:08 PM (EDT) · Next run Thu, Jul 23, 4:08 PM");
  });
});
