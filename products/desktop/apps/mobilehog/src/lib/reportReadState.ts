import type { QueryClient, QueryKey } from "@tanstack/react-query";

export interface ReadStateResult {
  data?: boolean;
  isError: boolean;
  isFetchedAfterMount: boolean;
}

export interface ReportReadStates {
  unread: ReadonlySet<string>;
  // Every state came from the server since mount, not only from the saved
  // cache, so a report read on another device does not count as unread.
  settled: boolean;
}

// Only a fresh, successful answer counts as unread. A cached value or a failed
// refresh counts as read, so stale or missing state never lights a dot or pops
// the deck.
export function summarizeReadStates(
  reportIds: readonly string[],
  results: readonly ReadStateResult[],
): ReportReadStates {
  const unread = new Set<string>();
  reportIds.forEach((id, index) => {
    const result = results[index];
    if (
      result?.data === false &&
      result.isFetchedAfterMount &&
      !result.isError
    ) {
      unread.add(id);
    }
  });
  return {
    unread,
    settled: results.every((result) => result.isFetchedAfterMount),
  };
}

export async function markReadOptimistically(
  queryClient: QueryClient,
  key: QueryKey,
): Promise<boolean | undefined> {
  await queryClient.cancelQueries({ queryKey: key, exact: true });
  const previous = queryClient.getQueryData<boolean>(key);
  queryClient.setQueryData(key, true);
  return previous;
}

// Put back what the cache held before the failed write, so the next open does
// not see the report as read and tries the write again.
export async function restoreReadState(
  queryClient: QueryClient,
  key: QueryKey,
  previous: boolean | undefined,
): Promise<void> {
  if (previous === undefined) {
    await queryClient.resetQueries({ queryKey: key, exact: true });
    return;
  }
  queryClient.setQueryData(key, previous);
  await queryClient.invalidateQueries({ queryKey: key, exact: true });
}
