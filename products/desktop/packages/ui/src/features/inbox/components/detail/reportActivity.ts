import type { AnySignalReportArtefact } from "@posthog/shared/types";

const ROUTINE_PIPELINE_ARTEFACTS = new Set([
  "actionability_judgment",
  "impact_measurement_plan",
  "priority_judgment",
  "repo_selection",
  "safety_judgment",
  "signal_finding",
  "suggested_reviewers",
  "task_run",
]);

export function selectUsefulReportActivity(
  artefacts: AnySignalReportArtefact[],
): AnySignalReportArtefact[] {
  return artefacts.filter(
    (artefact) => !ROUTINE_PIPELINE_ARTEFACTS.has(artefact.type),
  );
}
