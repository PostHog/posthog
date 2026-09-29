import type { AnySignalReportArtefact } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import { selectUsefulReportActivity } from "./reportActivity";

function artefact(type: string, degraded = false): AnySignalReportArtefact {
  return {
    id: degraded ? `${type}-degraded` : type,
    type,
    degraded,
    created_at: "2026-01-01T00:00:00Z",
    content: {
      session_id: "",
      start_time: "",
      end_time: "",
      distinct_id: "",
      content: "",
      distance_to_centroid: null,
    },
  };
}

describe("selectUsefulReportActivity", () => {
  it("removes routine pipeline records while preserving useful progress", () => {
    const result = selectUsefulReportActivity([
      artefact("task_run"),
      artefact("safety_judgment"),
      artefact("signal_finding"),
      artefact("impact_measurement_plan"),
      artefact("impact_measurement_plan", true),
      artefact("commit"),
      artefact("note"),
    ]);

    expect(result.map((entry) => entry.id)).toEqual([
      "impact_measurement_plan-degraded",
      "commit",
      "note",
    ]);
  });
});
