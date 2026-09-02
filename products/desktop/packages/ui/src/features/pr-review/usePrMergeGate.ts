import { usePrChecks } from "./usePrChecks";
import { usePrInfo } from "./usePrInfo";

export interface PrMergeGate {
  /** Undefined until the PR info query resolves. */
  info: ReturnType<typeof usePrInfo>["data"];
  merged: boolean;
  closed: boolean;
  draft: boolean;
  failedChecks: number;
  pendingChecks: number;
  totalChecks: number;
  /** True once the checks query has settled with data. */
  checksLoaded: boolean;
  /** Failed fetch (null / error): CI status is unknown, which locks the merge. */
  checksUnavailable: boolean;
  /** Human-readable reason the merge is locked, or null when it isn't. */
  mergeBlockedReason: string | null;
}

/**
 * The merge gate for a PR, shared by every surface that offers approve/merge:
 * mirrors github.com's own rules (red checks, conflicts, branch protection,
 * out-of-date branch, unknown CI all lock the merge). One source of truth so
 * a big merge button and a compact one can never disagree on when it's safe.
 */
export function usePrMergeGate(prUrl: string): PrMergeGate {
  const infoQuery = usePrInfo(prUrl);
  // Shares the checks section's polling query, so the gate follows CI live:
  // it locks as soon as a check goes red and unlocks on a green rerun.
  const checksQuery = usePrChecks(prUrl);

  const info = infoQuery.data;
  const merged = info?.merged ?? false;
  const closed = !merged && info?.state?.toLowerCase() === "closed";
  const draft = info?.draft ?? false;
  const checks = checksQuery.data ?? [];
  // Cancelled counts as failed, matching the feed summary and PR chip — a
  // cancelled check never succeeded, so it must not read as "all passed".
  const failedChecks = checks.filter(
    (check) => check.bucket === "fail" || check.bucket === "cancel",
  ).length;
  const pendingChecks = checks.filter(
    (check) => check.bucket === "pending",
  ).length;
  const hasConflicts = info?.mergeable === false;
  // Failed fetch (null / error) means CI status is unknown — that must lock
  // the merge too, or a transient gh error would silently unlock red checks.
  const checksUnavailable = checksQuery.isError || checksQuery.data === null;
  // Branch protection ("blocked") is viewer-aware: it covers repos that
  // require an approving review — including the PR author, who can't approve
  // their own PR. Repos without such rules report "clean"/"unstable".
  const blockedByProtection = info?.mergeStateStatus === "blocked";
  const behindBase = info?.mergeStateStatus === "behind";
  const mergeBlockedReason = draft
    ? null // draft state renders its own note + CTA
    : failedChecks > 0
      ? `${failedChecks} check${failedChecks === 1 ? " is" : "s are"} failing. Merging is blocked until they pass.`
      : hasConflicts
        ? "This branch has conflicts that must be resolved before merging."
        : blockedByProtection
          ? "Branch protection blocks this merge. An approving review from another user may be required."
          : behindBase
            ? "This branch is out of date with the base branch and must be updated before merging."
            : checksUnavailable
              ? "CI status couldn't be loaded. Merging is blocked until checks are known."
              : null;

  return {
    info,
    merged,
    closed,
    draft,
    failedChecks,
    pendingChecks,
    totalChecks: checks.length,
    checksLoaded: checksQuery.data != null,
    checksUnavailable,
    mergeBlockedReason,
  };
}
