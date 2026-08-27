// Space collections stay visible while they revalidate. Only mounted (active)
// space queries poll; inactive spaces remain cached for fast switching.
export const SPACE_QUERY_STALE_TIME_MS = 15_000;
export const SPACE_QUERY_GC_TIME_MS = 30 * 60_000;
export const SPACE_QUERY_REFETCH_INTERVAL_MS = 15_000;
