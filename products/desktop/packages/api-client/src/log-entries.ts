import type { StoredLogEntry } from "@posthog/shared";

export interface TaskRunSessionLogsPage {
  entries: StoredLogEntry[];
  hasMore: boolean;
  matchingCount: number | null;
}

function parseCountHeader(headers: Headers, name: string): number | null {
  // Number(null) is 0, so an absent header must stay null.
  const value = headers.get(name);
  if (value === null) return null;
  const count = Number(value);
  return Number.isFinite(count) ? count : null;
}

export function parseLogEntriesPage(
  body: string,
  headers: Headers,
  start: number,
): TaskRunSessionLogsPage {
  const offset = parseCountHeader(headers, "X-Log-Offset");
  if (offset !== start) {
    throw new Error(`Log entries page starts at ${offset}, not ${start}`);
  }
  const entries = body
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as StoredLogEntry);
  const matchingCount = parseCountHeader(headers, "X-Log-Count");
  return {
    entries,
    hasMore: matchingCount !== null && offset + entries.length < matchingCount,
    matchingCount,
  };
}
