import type {
  ScoutConfig,
  ScoutSuggestionItem,
} from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  suggestionMetaLine,
  suggestionToCreateInput,
  visibleScoutSuggestions,
} from "./scoutSuggestions";

const suggestion = (
  overrides: Partial<ScoutSuggestionItem> = {},
): ScoutSuggestionItem => ({
  id: "suggestion-1",
  kind: "custom",
  skill_name: "signals-scout-checkout-funnel",
  title: "Watch the checkout funnel",
  why_here: "Checkout drop-off moved twice last month.",
  description: "Investigates conversion through checkout.",
  draft_body: "# Checkout funnel\n\nCheck the funnel every run.",
  proposed_config: {
    run_cron_schedule: null,
    run_interval_minutes: null,
    emit: true,
  },
  gap: true,
  confidence: "high",
  ...overrides,
});

const config = (overrides: Partial<ScoutConfig>): ScoutConfig =>
  ({
    id: "config-1",
    skill_name: "signals-scout-error-tracking",
    enabled: true,
    emit: true,
    run_interval_minutes: 1440,
    last_run_at: null,
    created_at: "2026-06-01T00:00:00Z",
    ...overrides,
  }) as ScoutConfig;

describe("scoutSuggestions", () => {
  it("hides a pick the roster has already switched on", () => {
    const items = [
      suggestion({ id: "a", kind: "canonical", skill_name: "signals-scout-a" }),
      suggestion({ id: "b", skill_name: "signals-scout-b" }),
    ];

    const visible = visibleScoutSuggestions(items, {
      hiddenIds: [],
      configs: [config({ skill_name: "signals-scout-a", enabled: true })],
    });

    expect(visible.map((item) => item.id)).toEqual(["b"]);
  });

  // A scout switched off is exactly what the batch should keep offering.
  it("keeps a pick whose scout exists but is off", () => {
    const items = [suggestion({ id: "a", skill_name: "signals-scout-a" })];

    const visible = visibleScoutSuggestions(items, {
      hiddenIds: [],
      configs: [config({ skill_name: "signals-scout-a", enabled: false })],
    });

    expect(visible.map((item) => item.id)).toEqual(["a"]);
  });

  it("hides a pick dismissed since the last read", () => {
    const visible = visibleScoutSuggestions([suggestion({ id: "a" })], {
      hiddenIds: ["a"],
      configs: [],
    });

    expect(visible).toEqual([]);
  });

  it("creates a pick that names no schedule on the daily default", () => {
    expect(suggestionToCreateInput(suggestion()).config).toEqual({
      enabled: true,
      emit: true,
      run_cron_schedule: null,
      run_interval_minutes: 1440,
    });
  });

  it("carries the suggestion id, so the batch stops offering it", () => {
    expect(suggestionToCreateInput(suggestion()).suggestion_id).toBe(
      "suggestion-1",
    );
  });

  it("names the cadence and the dry-run posture in one line", () => {
    expect(
      suggestionMetaLine({
        run_cron_schedule: "30 9 * * *",
        run_interval_minutes: null,
        emit: false,
      }),
    ).toBe("Runs daily at 09:30 · dry run, files nothing");
  });
});
