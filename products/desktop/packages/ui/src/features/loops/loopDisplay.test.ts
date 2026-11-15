import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  describeTrigger,
  loopStatusColor,
  loopStatusLabel,
  nextScheduleRun,
  summarizeNotificationDestinations,
  summarizeTrigger,
} from "./loopDisplay";

describe("loopStatusLabel and loopStatusColor", () => {
  it.each([
    [{ enabled: true, last_run_status: null }, "Active", "green"],
    [{ enabled: true, last_run_status: "failed" }, "Failing", "red"],
    [{ enabled: false, last_run_status: "failed" }, "Paused", "gray"],
  ])("derives label and color (%#)", (loop, label, color) => {
    expect(loopStatusLabel(loop)).toBe(label);
    expect(loopStatusColor(loop)).toBe(color);
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

  // A workflow can carry a schedule trigger with no schedule row yet.
  it("names a schedule trigger with no cron as unset", () => {
    expect(describeTrigger({ type: "schedule", config: {} })).toBe(
      "Schedule · No schedule set",
    );
  });

  it("keeps custom cron expressions visible", () => {
    expect(
      describeTrigger({
        type: "schedule",
        config: { cron_expression: "*/15 * * * *", timezone: "UTC" },
      }),
    ).toBe("Schedule · */15 * * * * (UTC)");
  });

  it("describes a github trigger by repository and event", () => {
    expect(
      describeTrigger({
        type: "github",
        config: {
          github_integration_id: 7,
          repository: "posthog/posthog",
          events: ["pull_request"],
        },
      }),
    ).toBe("GitHub · posthog/posthog · pull_request");
  });
});

describe("summarizeNotificationDestinations", () => {
  it("lists enabled destinations and includes the Slack channel", () => {
    expect(
      summarizeNotificationDestinations({
        email: { enabled: true, params: {} },
        slack: { enabled: true, params: { channel_name: "#loops" } },
      }),
    ).toEqual(["Email", "Slack · #loops"]);
  });

  it("omits disabled destinations", () => {
    expect(
      summarizeNotificationDestinations({
        email: { enabled: false, params: {} },
        slack: { enabled: false, params: {} },
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
