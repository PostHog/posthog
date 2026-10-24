import { getRelativeDateGroup } from "@posthog/shared";
import type {
  Command,
  CommandSection,
} from "@posthog/ui/features/command/commandRow";

export type ObjectSort = "recent" | "created" | "name";

export const DEFAULT_OBJECT_SORT: ObjectSort = "recent";

export const OBJECT_SORT_OPTIONS: readonly {
  value: ObjectSort;
  label: string;
}[] = [
  { value: "recent", label: "Recent" },
  { value: "created", label: "Created" },
  { value: "name", label: "Name" },
];

export function isObjectSort(value: unknown): value is ObjectSort {
  return OBJECT_SORT_OPTIONS.some((option) => option.value === value);
}

export function nextObjectSort(sort: ObjectSort): ObjectSort {
  const index = OBJECT_SORT_OPTIONS.findIndex(
    (option) => option.value === sort,
  );
  return OBJECT_SORT_OPTIONS[(index + 1) % OBJECT_SORT_OPTIONS.length].value;
}

export interface SortableObjectRow {
  command: Command;
  /** When the viewer last opened the object. Absent when they never did. */
  viewedAt?: number;
  createdAt?: number;
}

export interface SortedObjectRow {
  command: Command;
  /** The date separator above the row. Null for a sort with no dates. */
  group: string | null;
}

const NOT_OPENED_GROUP = "Not opened yet";
const NO_DATE_GROUP = "No date";

const nameCollator = new Intl.Collator(undefined, {
  sensitivity: "base",
  numeric: true,
});

function isTimestamp(value: number | undefined): value is number {
  return value != null && Number.isFinite(value);
}

function dateGroup(timestamp: number): string {
  // A clock ahead of ours would otherwise fall out of every bucket.
  return getRelativeDateGroup(Math.min(timestamp, Date.now())) ?? "Today";
}

/**
 * Orders the rows of one object type. A date sort puts the newest first and
 * gives each row the date bucket it falls in. Rows without that date go last,
 * in their input order, under a group that says why.
 */
export function sortObjectRows(
  rows: readonly SortableObjectRow[],
  sort: ObjectSort,
): SortedObjectRow[] {
  if (sort === "name") {
    return [...rows]
      .sort((left, right) =>
        nameCollator.compare(left.command.label, right.command.label),
      )
      .map((row) => ({ command: row.command, group: null }));
  }
  const dateOf = (row: SortableObjectRow) =>
    sort === "recent" ? row.viewedAt : row.createdAt;
  const dated = rows
    .filter((row) => isTimestamp(dateOf(row)))
    .sort((left, right) => (dateOf(right) ?? 0) - (dateOf(left) ?? 0))
    .map((row) => ({
      command: row.command,
      group: dateGroup(dateOf(row) ?? 0),
    }));
  const undatedGroup = sort === "recent" ? NOT_OPENED_GROUP : NO_DATE_GROUP;
  const undated = rows
    .filter((row) => !isTimestamp(dateOf(row)))
    .map((row) => ({ command: row.command, group: undatedGroup }));
  return [...dated, ...undated];
}

/** One section per run of rows that share a group. Rows without one use `label`. */
export function objectRowSections(
  rows: readonly SortedObjectRow[],
  label: string,
): CommandSection[] {
  const sections: CommandSection[] = [];
  for (const row of rows) {
    const sectionLabel = row.group ?? label;
    const last = sections[sections.length - 1];
    if (last && last.label === sectionLabel) last.items.push(row.command);
    else sections.push({ label: sectionLabel, items: [row.command] });
  }
  return sections;
}
