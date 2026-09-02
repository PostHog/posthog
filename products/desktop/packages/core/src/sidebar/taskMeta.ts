export interface RawTaskTimestamp {
  pinnedAt: string | null;
  lastViewedAt: string | null;
  lastActivityAt: string | null;
}

export interface TaskTimestamps {
  lastViewedAt: number | null;
  lastActivityAt: number | null;
}

export function parseTimestamps(
  raw: Record<string, RawTaskTimestamp>,
): Record<string, TaskTimestamps> {
  const result: Record<string, TaskTimestamps> = {};
  for (const [taskId, ts] of Object.entries(raw)) {
    result[taskId] = {
      lastViewedAt: ts.lastViewedAt
        ? new Date(ts.lastViewedAt).getTime()
        : null,
      lastActivityAt: ts.lastActivityAt
        ? new Date(ts.lastActivityAt).getTime()
        : null,
    };
  }
  return result;
}
