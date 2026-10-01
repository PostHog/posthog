export interface ReadStateResult {
  data?: boolean;
  isFetchedAfterMount: boolean;
}

export interface ReportReadStates {
  unread: ReadonlySet<string>;
  // Every state came from the server since mount, not only from the saved
  // cache, so a report read on another device does not count as unread.
  settled: boolean;
}

// A state that failed to load counts as read, so an error never lights a dot
// or pops the deck.
export function summarizeReadStates(
  reportIds: readonly string[],
  results: readonly ReadStateResult[],
): ReportReadStates {
  const unread = new Set<string>();
  reportIds.forEach((id, index) => {
    if (results[index]?.data === false) unread.add(id);
  });
  return {
    unread,
    settled: results.every((result) => result.isFetchedAfterMount),
  };
}
