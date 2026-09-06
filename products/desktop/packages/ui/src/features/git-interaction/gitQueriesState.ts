interface ChangesLoadingInput {
  /** The hook is active — a repo path exists and the consumer enabled it. */
  enabled: boolean;
  /** validateRepo has not yet confirmed whether the path is a repo. */
  isRepoLoading: boolean;
  /** The path is a confirmed repo, so the changed-files query can run. */
  repoEnabled: boolean;
  /** The changed-files query has no data yet (pending, or still disabled). */
  changesPending: boolean;
}

/**
 * True while the changed-files list is still resolving.
 *
 * The changed-files query stays disabled until validateRepo confirms the repo,
 * and a disabled query reports isLoading=false while it holds no data. A raw
 * isLoading therefore reads as "loaded" during the validation window, which
 * lets the review panel drop its spinner and render a partial file list.
 * Untracked files come only from that query, so the panel then shows an empty
 * or incomplete diff. Report the validation window and the first fetch as
 * loading instead. Cached data (a reopen) clears changesPending, so a warm
 * panel does not spin.
 */
export function resolveChangesLoading({
  enabled,
  isRepoLoading,
  repoEnabled,
  changesPending,
}: ChangesLoadingInput): boolean {
  if (!enabled) return false;
  return isRepoLoading || (repoEnabled && changesPending);
}
