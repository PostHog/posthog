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
  // A malformed plan degrades to a preview that the expected-impact section
  // skips, so keep it here rather than let it vanish from both.
  return artefacts.filter(
    (artefact) =>
      (artefact.type === "impact_measurement_plan" && artefact.degraded) ||
      !ROUTINE_PIPELINE_ARTEFACTS.has(artefact.type),
  );
}
