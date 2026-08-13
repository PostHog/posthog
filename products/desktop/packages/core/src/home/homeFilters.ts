import type { HomeRow } from "./homeRows";
import {
  HOME_STATUS_LABELS,
  HOME_STATUS_ORDER,
  HOME_WORK_KIND_LABELS,
  type HomeStatus,
  type HomeWorkKind,
} from "./schemas";

/**
 * What the table is narrowed to. Each facet is a set of accepted values, and an
 * empty set means "don't narrow on this" rather than "match nothing" — a filter
 * nobody has touched should never hide a row.
 */
export interface HomeFilters {
  statuses: readonly HomeStatus[];
  kinds: readonly HomeWorkKind[];
  spaceIds: readonly string[];
  projectIds: readonly string[];
  /** User uuids. Work with no assignee matches only when this is empty. */
  assigneeUuids: readonly string[];
}

export const NO_HOME_FILTERS: HomeFilters = {
  statuses: [],
  kinds: [],
  spaceIds: [],
  projectIds: [],
  assigneeUuids: [],
};

export type HomeGroupBy = "status" | "project" | "space" | "assignee" | "none";
export type HomeSort = "recent" | "created" | "alpha" | "status";

export const HOME_GROUP_BY_LABELS: Record<HomeGroupBy, string> = {
  status: "Status",
  project: "Project",
  space: "Space",
  assignee: "Assignee",
  none: "Nothing",
};

export const HOME_SORT_LABELS: Record<HomeSort, string> = {
  recent: "Last updated",
  created: "Created",
  alpha: "Title",
  status: "Status",
};

/** How many filters are narrowing the table, which the filter button carries. */
export function countHomeFilters(filters: HomeFilters): number {
  return (
    filters.statuses.length +
    filters.kinds.length +
    filters.spaceIds.length +
    filters.projectIds.length +
    filters.assigneeUuids.length
  );
}

/** Add or remove one value of a facet, leaving the rest of the filters alone. */
export function toggleHomeFilter<K extends keyof HomeFilters>(
  filters: HomeFilters,
  facet: K,
  value: HomeFilters[K][number],
): HomeFilters {
  const current = filters[facet] as readonly string[];
  const next = current.includes(value as string)
    ? current.filter((entry) => entry !== value)
    : [...current, value as string];
  return { ...filters, [facet]: next };
}

function matches(accepted: readonly string[], value: string | null): boolean {
  if (accepted.length === 0) return true;
  return value != null && accepted.includes(value);
}

/**
 * The rows a query and a set of filters leave. The query is matched against
 * everything a reader can see on the row — title, project, space, reference —
 * so typing a space name finds its work without opening the filter menu.
 */
export function filterHomeRows(
  rows: readonly HomeRow[],
  { query, filters }: { query: string; filters: HomeFilters },
): HomeRow[] {
  const needle = query.trim().toLowerCase();
  return rows.filter((row) => {
    if (!matches(filters.statuses, row.status)) return false;
    if (!matches(filters.kinds, row.kind)) return false;
    if (!matches(filters.spaceIds, row.spaceId)) return false;
    if (!matches(filters.projectIds, row.projectId)) return false;
    if (!matches(filters.assigneeUuids, row.assignee?.uuid ?? null)) {
      return false;
    }
    if (!needle) return true;
    return [row.title, row.projectName, row.spaceName, row.reference]
      .filter((field): field is string => !!field)
      .some((field) => field.toLowerCase().includes(needle));
  });
}

const STATUS_RANK = new Map(
  HOME_STATUS_ORDER.map((status, index) => [status, index]),
);

function statusRank(status: HomeStatus): number {
  return STATUS_RANK.get(status) ?? HOME_STATUS_ORDER.length;
}

/**
 * Pinned work first, then the chosen order. Pinning is the reader's own filing
 * and outranks every sort, the same way it does in the space's session list.
 */
export function sortHomeRows(
  rows: readonly HomeRow[],
  sort: HomeSort,
): HomeRow[] {
  const compare = (a: HomeRow, b: HomeRow): number => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    switch (sort) {
      case "created":
        return b.createdAt - a.createdAt;
      case "alpha":
        return a.title.localeCompare(b.title);
      case "status": {
        const byStatus = statusRank(a.status) - statusRank(b.status);
        return byStatus === 0 ? b.updatedAt - a.updatedAt : byStatus;
      }
      default:
        return b.updatedAt - a.updatedAt;
    }
  };
  return [...rows].sort(compare);
}

/** One section of the table: a heading, and the rows filed under it. */
export interface HomeGroup {
  /** Stable across renders and across data refreshes — collapse state keys on it. */
  key: string;
  label: string;
  rows: HomeRow[];
}

/** The heading a row falls under, or null when it has no value for the facet. */
function groupKeyFor(
  row: HomeRow,
  groupBy: Exclude<HomeGroupBy, "none">,
): { key: string; label: string } | null {
  switch (groupBy) {
    case "status":
      return { key: row.status, label: HOME_STATUS_LABELS[row.status] };
    case "project":
      return row.projectId && row.projectName
        ? { key: row.projectId, label: row.projectName }
        : null;
    case "space":
      return { key: row.spaceId, label: `#${row.spaceName}` };
    case "assignee":
      return row.assignee
        ? {
            key: row.assignee.uuid,
            label:
              [row.assignee.first_name, row.assignee.last_name]
                .filter(Boolean)
                .join(" ") ||
              row.assignee.email ||
              "Unknown",
          }
        : null;
  }
}

/**
 * The heading for rows that have no value for the facet being grouped on:
 * unfiled work, or work nobody has picked up. It sorts last, because it is the
 * pile you deal with after the named ones. Exported because the table treats it
 * differently from a real heading: there is no project to add work to.
 */
export const UNGROUPED_GROUP_KEY = "__ungrouped__";

const UNGROUPED_LABELS: Record<Exclude<HomeGroupBy, "none">, string> = {
  status: "No status",
  project: "No project",
  space: "No space",
  assignee: "Unassigned",
};

/**
 * Split rows into the table's sections. Grouping by status keeps every status
 * in its canonical order and drops the empty ones; every other facet is ordered
 * by how much work sits under it, so the busiest heading leads.
 */
export function groupHomeRows(
  rows: readonly HomeRow[],
  groupBy: HomeGroupBy,
): HomeGroup[] {
  if (groupBy === "none") {
    return [{ key: "all", label: "All work", rows: [...rows] }];
  }

  const groups = new Map<string, HomeGroup>();
  for (const row of rows) {
    const target = groupKeyFor(row, groupBy) ?? {
      key: UNGROUPED_GROUP_KEY,
      label: UNGROUPED_LABELS[groupBy],
    };
    const existing = groups.get(target.key);
    if (existing) {
      existing.rows.push(row);
    } else {
      groups.set(target.key, { ...target, rows: [row] });
    }
  }

  if (groupBy === "status") {
    return HOME_STATUS_ORDER.map((status) => groups.get(status)).filter(
      (group): group is HomeGroup => group != null,
    );
  }

  return [...groups.values()].sort((a, b) => {
    if (a.key === UNGROUPED_GROUP_KEY) return 1;
    if (b.key === UNGROUPED_GROUP_KEY) return -1;
    const byCount = b.rows.length - a.rows.length;
    return byCount === 0 ? a.label.localeCompare(b.label) : byCount;
  });
}

/** One offerable value of a facet, with how much work carries it. */
export interface HomeFacetOption<T extends string = string> {
  value: T;
  label: string;
  count: number;
}

export interface HomeFacets {
  statuses: HomeFacetOption<HomeStatus>[];
  kinds: HomeFacetOption<HomeWorkKind>[];
  spaces: HomeFacetOption[];
  projects: HomeFacetOption[];
  assignees: HomeFacetOption[];
}

/**
 * The facet values actually present in a set of rows, so the filter menu only
 * offers what can match. Statuses and kinds keep their canonical order; the
 * rest come back alphabetical, so the menu is stable between refreshes.
 */
export function homeFacets(rows: readonly HomeRow[]): HomeFacets {
  const tally = <T extends string>(
    pick: (row: HomeRow) => { value: T; label: string } | null,
  ): Map<T, { label: string; count: number }> => {
    const counts = new Map<T, { label: string; count: number }>();
    for (const row of rows) {
      const entry = pick(row);
      if (!entry) continue;
      const existing = counts.get(entry.value);
      if (existing) existing.count += 1;
      else counts.set(entry.value, { label: entry.label, count: 1 });
    }
    return counts;
  };

  const statusCounts = tally<HomeStatus>((row) => ({
    value: row.status,
    label: HOME_STATUS_LABELS[row.status],
  }));
  const kindCounts = tally<HomeWorkKind>((row) => ({
    value: row.kind,
    label: HOME_WORK_KIND_LABELS[row.kind],
  }));
  const alphabetical = <T extends string>(
    counts: Map<T, { label: string; count: number }>,
  ) =>
    [...counts.entries()]
      .map(([value, entry]) => ({ value, ...entry }))
      .sort((a, b) => a.label.localeCompare(b.label));

  return {
    statuses: HOME_STATUS_ORDER.flatMap((status) => {
      const entry = statusCounts.get(status);
      return entry ? [{ value: status, ...entry }] : [];
    }),
    kinds: (["session", "canvas", "plan", "todo"] as const).flatMap((kind) => {
      const entry = kindCounts.get(kind);
      return entry ? [{ value: kind, ...entry }] : [];
    }),
    spaces: alphabetical(
      tally((row) => ({ value: row.spaceId, label: `#${row.spaceName}` })),
    ),
    projects: alphabetical(
      tally((row) =>
        row.projectId && row.projectName
          ? { value: row.projectId, label: row.projectName }
          : null,
      ),
    ),
    assignees: alphabetical(
      tally((row) => {
        const assignee = row.assignee;
        if (!assignee) return null;
        return {
          value: assignee.uuid,
          label:
            [assignee.first_name, assignee.last_name]
              .filter(Boolean)
              .join(" ") ||
            assignee.email ||
            "Unknown",
        };
      }),
    ),
  };
}
