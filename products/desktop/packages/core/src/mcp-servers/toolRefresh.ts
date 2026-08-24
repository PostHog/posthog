export interface AutoRefreshState {
  autoRefreshIfEmpty: boolean;
  installationId: string | null;
  isLoading: boolean;
  toolsLength: number;
  alreadyRefreshed: boolean;
  refreshPending: boolean;
}

export function shouldAutoRefreshTools(state: AutoRefreshState): boolean {
  if (!state.autoRefreshIfEmpty) return false;
  if (!state.installationId) return false;
  if (state.isLoading) return false;
  if (state.toolsLength > 0) return false;
  if (state.alreadyRefreshed) return false;
  if (state.refreshPending) return false;
  return true;
}

/**
 * A silent auto-refresh retries a failed listing this many times before giving
 * up for the mount, so a flaky or rate-limited upstream gets a few spaced
 * attempts and a broken one gets a bounded number of requests.
 */
export const AUTO_REFRESH_MAX_RETRIES = 2;

/** Exponential backoff between silent auto-refresh retries: 1s, then 2s. */
export function autoRefreshRetryDelayMs(failureCount: number): number {
  return 1000 * 2 ** failureCount;
}

/**
 * Only the silent auto-refresh retries. A manual refresh reports its first
 * failure so the user is not left waiting behind a backoff.
 */
export function shouldRetryAutoRefresh(
  failureCount: number,
  silent: boolean,
): boolean {
  return silent && failureCount < AUTO_REFRESH_MAX_RETRIES;
}
