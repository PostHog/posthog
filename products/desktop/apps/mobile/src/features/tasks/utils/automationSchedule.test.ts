import { describe, expect, it } from "vitest";
import {
  buildCronExpression,
  createDefaultScheduleDraft,
  deriveAutomationName,
  formatScheduleSummary,
  parseCronExpression,
} from "./automationSchedule";

describe("automationSchedule", () => {
  it("builds cron expressions for common schedule presets", () => {
    expect(
      buildCronExpression({
        ...createDefaultScheduleDraft(),
        mode: "hourly",
        minute: "15",
      }),
    ).toBe("15 * * * *");

    expect(
      buildCronExpression({
        ...createDefaultScheduleDraft(),
        mode: "daily",
        hour: "09",
        minute: "15",
      }),
    ).toBe("15 9 * * *");

    expect(
      buildCronExpression({
        ...createDefaultScheduleDraft(),
        mode: "weekdays",
        hour: "10",
        minute: "00",
      }),
    ).toBe("0 10 * * 1-5");

    expect(
      buildCronExpression({
        ...createDefaultScheduleDraft(),
        mode: "weekly",
        hour: "11",
        minute: "30",
        weekday: "4",
      }),
    ).toBe("30 11 * * 4");
  });

  it("parses common cron expressions back into schedule drafts", () => {
    expect(parseCronExpression("15 * * * *")).toMatchObject({
      mode: "hourly",
      minute: "15",
    });

    expect(parseCronExpression("0 9 * * *")).toMatchObject({
      mode: "daily",
      hour: "09",
      minute: "00",
    });

    expect(parseCronExpression("0 9 * * 1-5")).toMatchObject({
      mode: "weekdays",
      hour: "09",
      minute: "00",
    });

    expect(parseCronExpression("30 14 * * 2")).toMatchObject({
      mode: "weekly",
      weekday: "2",
      hour: "14",
      minute: "30",
    });
  });

  it("keeps custom cron expressions in custom mode", () => {
    expect(parseCronExpression("*/15 * * * *")).toMatchObject({
      mode: "custom",
      rawCron: "*/15 * * * *",
    });
  });

  it("derives a readable automation name from the prompt", () => {
    expect(
      deriveAutomationName(
        "\n  Review every open PostHog PR for stale comments \n",
      ),
    ).toBe("Review every open PostHog PR for stale comments");
  });

  it("formats schedule summaries with timezone context", () => {
    expect(formatScheduleSummary("15 * * * *", "Europe/London")).toBe(
      "Every hour at :15 · Europe/London",
    );
    expect(formatScheduleSummary("0 9 * * 1-5", "Europe/London")).toBe(
      "Weekdays at 09:00 · Europe/London",
    );
    expect(formatScheduleSummary("*/15 * * * *", "UTC")).toBe(
      "Custom schedule · UTC",
    );
  });
});
