import type { Signal, SignalReport } from "@posthog/shared/types";

export function inboxStoryReport(
  overrides: Partial<SignalReport> = {},
): SignalReport {
  return {
    id: "story-report",
    title: "fix(cohorts): keep recurring calculations within their budget",
    summary:
      "Recurring cohort calculations can overlap after a delayed run, which increases queue time for later updates.\n\n## Impact\n\nTeams see stale cohort membership until the overlapping calculations finish.\n\n## Recommendation\n\nCoalesce pending work by cohort and carry the newest requested calculation forward.",
    status: "ready",
    total_weight: 48,
    signal_count: 6,
    created_at: "2026-08-20T09:00:00Z",
    updated_at: "2026-08-28T14:30:00Z",
    artefact_count: 3,
    priority: "P1",
    actionability: "immediately_actionable",
    is_suggested_reviewer: true,
    source_products: ["signals_scout"],
    ...overrides,
  };
}

export function inboxStorySignal(overrides: Partial<Signal> = {}): Signal {
  return {
    signal_id: "story-signal",
    content:
      "The calculated membership remained unchanged after the scheduled update completed.",
    source_product: "signals_scout",
    source_type: "cross_source_issue",
    source_id: "story-source",
    weight: 8,
    timestamp: "2026-08-27T12:00:00Z",
    extra: { skill_name: "signals-scout-data-quality" },
    ...overrides,
  };
}
