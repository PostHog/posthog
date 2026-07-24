import type {
  ActionabilityJudgmentArtefact,
  ActionabilityJudgmentContent,
  PriorityJudgmentArtefact,
  SignalFindingArtefact,
  SignalReportArtefactsResponse,
  SuggestedReviewer,
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

export function selectSuggestedReviewers(
  artefacts: ReportArtefact[],
  meUuid?: string,
): SuggestedReviewer[] {
  const artefact = latestOfType<SuggestedReviewersArtefact>(
    artefacts,
    "suggested_reviewers",
  );
  const reviewers = artefact?.content ?? [];
  if (!meUuid) return reviewers;
  const meIndex = reviewers.findIndex((r) => r.user?.uuid === meUuid);
  if (meIndex <= 0) return reviewers;
  return [reviewers[meIndex], ...reviewers.filter((_, i) => i !== meIndex)];
}

export function buildSignalFindingMap(
  artefacts: ReportArtefact[],
): Map<string, SignalFindingArtefact["content"]> {
  const latestBySignal = new Map<string, SignalFindingArtefact>();
  for (const a of artefacts) {
    if (a.type !== "signal_finding") continue;
    const finding = a as SignalFindingArtefact;
    const existing = latestBySignal.get(finding.content.signal_id);
    if (!existing || finding.created_at > existing.created_at) {
      latestBySignal.set(finding.content.signal_id, finding);
    }
  }
  const map = new Map<string, SignalFindingArtefact["content"]>();
  for (const [signalId, finding] of latestBySignal) {
    map.set(signalId, finding.content);
  }
  return map;
}

export function selectActionabilityJudgment(
  artefacts: ReportArtefact[],
): ActionabilityJudgmentContent | null {
  return (
    latestOfType<ActionabilityJudgmentArtefact>(
      artefacts,
      "actionability_judgment",
    )?.content ?? null
  );
}

export function selectPriorityExplanation(
  artefacts: ReportArtefact[],
): string | null {
  return (
    latestOfType<PriorityJudgmentArtefact>(artefacts, "priority_judgment")
      ?.content.explanation || null
  );
}
