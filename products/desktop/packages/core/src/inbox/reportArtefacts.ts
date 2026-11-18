import type {
  SignalReportArtefactsResponse,
  SuggestedReviewersArtefact,
} from "@posthog/shared/domain-types";

type ReportArtefact = SignalReportArtefactsResponse["results"][number];

// Artefacts are an append-only history: status types (judgments, reviewers) are
// latest-wins, and `signal_finding` is keyed by signal_id with the latest version
// per signal winning. ISO-8601 `created_at` strings compare lexicographically in
// chronological order, so selection is order-independent rather than relying on
// the API's `-created_at` response ordering.
function latestOfType<T extends ReportArtefact>(
  artefacts: ReportArtefact[],
  type: T["type"],
): T | null {
  let latest: T | null = null;
  for (const a of artefacts) {
    if (a.type === type && (!latest || a.created_at > latest.created_at)) {
      latest = a as T;
    }
  }
  return latest;
}

export function selectSuggestedReviewersArtefact(
  artefacts: ReportArtefact[],
): SuggestedReviewersArtefact | null {
  return latestOfType<SuggestedReviewersArtefact>(
    artefacts,
    "suggested_reviewers",
  );
}
