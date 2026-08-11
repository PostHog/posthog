import {
  extractSuggestedReviewers,
  suggestedReviewerDisplayName,
} from "@posthog/core/inbox/artefacts";
import { partitionSessionProblemSignals } from "@posthog/core/inbox/reportSignals";
import type {
  AnySignalReportArtefact,
  Signal,
} from "@posthog/shared/domain-types";

/**
 * The two compact strips the top swipe card borrows from the report detail
 * screen: how much work backs the report, and who is on the hook for it.
 *
 * Both are derived rather than rendered from the raw queries so the card can
 * decide whether a strip is worth any vertical space *before* laying it out —
 * a triage card with an empty "Findings" label reads as broken, not as
 * "nothing found yet".
 */

export interface CardEvidenceSummary {
  /** `signal_finding` artefacts — what the agent actually established. */
  findingCount: number;
  /** Session-replay problem signals, split out the way the detail page does. */
  replayCount: number;
}

/**
 * Evidence behind a report, or `null` when there is none worth a strip.
 *
 * Deliberately excludes the plain signal count: the card header already shows
 * `report.signal_count`, and repeating it here would spend a row saying
 * nothing new. Session-replay problems are counted separately for the same
 * reason the detail page partitions them out — they are evidence you watch,
 * not signals you read.
 */
export function summarizeCardEvidence(
  signals: Signal[] | undefined,
  artefacts: AnySignalReportArtefact[] | undefined,
): CardEvidenceSummary | null {
  const { evidence } = partitionSessionProblemSignals(signals ?? []);
  const findingCount = (artefacts ?? []).filter(
    (artefact) => artefact.type === "signal_finding",
  ).length;

  if (findingCount === 0 && evidence.length === 0) return null;
  return { findingCount, replayCount: evidence.length };
}

/**
 * Display names of the report's suggested reviewers, in artefact order.
 *
 * Unlike the detail screen this does not float the current user to the front:
 * doing so would cost the deck a user query per render for a strip that is
 * three names long and read at a glance. The card's "For you" state already
 * comes from the report's own `is_suggested_reviewer` flag.
 */
export function cardReviewerNames(
  artefacts: AnySignalReportArtefact[] | undefined,
): string[] {
  return extractSuggestedReviewers(artefacts)
    .map(suggestedReviewerDisplayName)
    .filter((name) => name.trim().length > 0);
}
