interface TimestampedEntry {
  id: string;
  created_at: string;
}

/**
 * One session of work often lands as several activity-log entries (a bulk tag
 * edit, an automation writing status + tags in one pass). They read as one
 * beat, so the list braces entries recorded within this window of each other.
 * Half a minute holds a human triaging field by field, and stays far short of
 * the gap between two people picking the ticket up at different times.
 */
export const ACTIVITY_GROUP_WINDOW_MS = 30_000;

export interface ActivityGroup<T extends TimestampedEntry> {
  /** React key: the first entry's id, stable across refetches. */
  key: string;
  entries: T[];
}

/**
 * Partition entries (already in display order) into runs recorded close
 * together. Adjacency chains: A, B, C group when each is within the window of
 * the one before it, which is how a burst actually arrives. Entries with an
 * unparseable timestamp never group.
 */
export function groupActivity<T extends TimestampedEntry>(
  entries: T[],
): ActivityGroup<T>[] {
  const groups: ActivityGroup<T>[] = [];
  let previousAt = Number.NaN;
  for (const entry of entries) {
    const at = new Date(entry.created_at).getTime();
    const last = groups[groups.length - 1];
    const nearPrevious =
      Number.isFinite(at) &&
      Number.isFinite(previousAt) &&
      Math.abs(at - previousAt) <= ACTIVITY_GROUP_WINDOW_MS;
    if (last && nearPrevious) {
      last.entries.push(entry);
    } else {
      groups.push({ key: entry.id, entries: [entry] });
    }
    previousAt = at;
  }
  return groups;
}
