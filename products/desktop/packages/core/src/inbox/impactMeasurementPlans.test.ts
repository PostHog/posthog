import type {
  AnySignalReportArtefact,
  ImpactMeasurementPlanArtefact,
  ImpactMeasurementPlanContent,
} from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import {
  impactMeasurementDecisionRule,
  impactMeasurementGoalLabel,
  selectImpactMeasurementPlans,
} from "./impactMeasurementPlans";

function plan(
  id: string,
  createdAt: string,
  content: Partial<ImpactMeasurementPlanContent> = {},
): ImpactMeasurementPlanArtefact {
  return {
    id,
    type: "impact_measurement_plan",
    created_at: createdAt,
    content: {
      metric_id: "errors",
      title: "Errors",
      activated: false,
      retired: false,
      ...content,
    },
  };
}

describe("selectImpactMeasurementPlans", () => {
  it("keeps the newest version of each metric regardless of response order", () => {
    const artefacts: AnySignalReportArtefact[] = [
      plan("old", "2026-09-01T00:00:00Z"),
      plan("other", "2026-09-02T00:00:00Z", { metric_id: "signups" }),
      plan("new", "2026-09-03T00:00:00Z", { activated: true }),
    ];

    expect(selectImpactMeasurementPlans(artefacts).map((a) => a.id)).toEqual([
      "new",
      "other",
    ]);
  });

  it("drops a metric whose newest version is retired", () => {
    const artefacts: AnySignalReportArtefact[] = [
      plan("proposed", "2026-09-01T00:00:00Z"),
      plan("retired", "2026-09-02T00:00:00Z", { retired: true }),
    ];

    expect(selectImpactMeasurementPlans(artefacts)).toEqual([]);
  });
});

describe("impact measurement copy", () => {
  it.each([
    [
      {
        goal_value: 10,
        goal_direction: "at_most" as const,
        value_format: "count" as const,
        unit: "errors",
      },
      "at most 10 errors",
    ],
    [
      {
        goal_value: 0.4,
        goal_direction: "at_least" as const,
        value_format: "percentage_scaled" as const,
      },
      "at least 40%",
    ],
    [{ goal_value: 5 }, null],
  ])("labels the goal %j as %s", (content, expected) => {
    expect(
      impactMeasurementGoalLabel(
        plan("p", "2026-09-01T00:00:00Z", content).content,
      ),
    ).toBe(expected);
  });

  it.each([
    [
      { decision_window_days: 7, minimum_data_points: 100 },
      "7 days after release and 100 qualifying observations",
    ],
    [{ decision_window_days: 1 }, "1 day after release"],
    [{}, null],
  ])("describes the decision rule %j as %s", (content, expected) => {
    expect(
      impactMeasurementDecisionRule(
        plan("p", "2026-09-01T00:00:00Z", content).content,
      ),
    ).toBe(expected);
  });
});
