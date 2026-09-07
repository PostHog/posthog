import type { ScoutSuggestionItem } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import { suggestionBrief, suggestionMetaLine } from "./scoutSuggestions";

describe("suggestionMetaLine", () => {
  it.each([
    [
      "a daily cron",
      {
        run_cron_schedule: "0 9 * * *",
        run_interval_minutes: null,
        emit: true,
      },
      "Runs daily at 09:00 · sends what it finds to Self-driving",
    ],
    [
      "no schedule at all",
      { run_cron_schedule: null, run_interval_minutes: null, emit: true },
      "Runs daily · sends what it finds to Self-driving",
    ],
    [
      "a dry run",
      {
        run_cron_schedule: null,
        run_interval_minutes: 180,
        emit: false,
      },
      "Runs every 3h · dry run, sends nothing",
    ],
  ])("reads back %s", (_name, config, expected) => {
    expect(suggestionMetaLine(config)).toBe(expected);
  });
});

describe("suggestionBrief", () => {
  const item = (description: string): ScoutSuggestionItem => ({
    id: "s1",
    kind: "custom",
    skill_name: "signals-scout-checkout-funnel",
    title: "Watch the checkout funnel for step drops",
    why_here: "This project sends checkout events every day.",
    description,
    draft_body: "",
    proposed_config: {
      run_cron_schedule: null,
      run_interval_minutes: null,
      emit: true,
    },
    gap: true,
    confidence: "high",
  });

  it("carries the description when there is one", () => {
    expect(suggestionBrief(item("Compare each step against last week."))).toBe(
      "Watch the checkout funnel for step drops. Compare each step against last week.",
    );
  });

  it("falls back to the title alone", () => {
    expect(suggestionBrief(item("  "))).toBe(
      "Watch the checkout funnel for step drops",
    );
  });
});
