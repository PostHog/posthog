import type {
  LinkedSignalReport,
  ScoutEmission,
  ScoutEmissionReportLink,
  ScoutRun,
} from "@posthog/api-client/posthog-client";
import { prettifyScoutSkillName } from "./scoutPresentation";

/**
 * Cross-fleet findings logic — the pure counterpart of the cloud `findingsLogic`.
 * Joins every recently-emitted scout finding to its run and the inbox report it
 * grouped into, then filters/sorts the flattened list. Kept host-agnostic so the
 * UI hook only wires queries; everything decision-shaped lives here and is unit
 * tested.
 */

/**
 * Fleet-wide cap on emitted runs we pull findings for. The runs window already
 * bounds this by time; this is a belt-and-braces ceiling so a burst of emitting
 * runs can't fan out into an unbounded batch request.
 */
export const MAX_FLEET_EMITTED_RUNS = 120;

export const SCOUT_FINDINGS_SCOUT_FILTER_ALL = "all";
export const SCOUT_FINDINGS_SEVERITY_FILTER_ALL = "all";

/** Severity options offered in the filter, most severe first. */
export const SCOUT_FINDINGS_SEVERITY_OPTIONS = [
  "P0",
  "P1",
  "P2",
  "P3",
  "P4",
] as const;

export type ScoutFindingsSortKey =
  | "newest"
  | "oldest"
  | "severity"
  | "confidence";

export interface ScoutFindingRow {
  emission: ScoutEmission;
  /** The run that emitted the finding — carries skill_name + the task-run link. */
  run: ScoutRun;
  /** The inbox report this finding's signal grouped into, when resolved. */
  linkedReport: LinkedSignalReport | null;
}

export interface ScoutFindingsFilter {
  search: string;
  /** A `skill_name`, or {@link SCOUT_FINDINGS_SCOUT_FILTER_ALL}. */
  scout: string;
  /** A severity (`P0`–`P4`), or {@link SCOUT_FINDINGS_SEVERITY_FILTER_ALL}. */
  severity: string;
  sort: ScoutFindingsSortKey;
}

export interface ScoutFilterOption {
  skillName: string;
  label: string;
  count: number;
}

export interface ScoutFindingsSummary {
  totalCount: number;
  scoutCount: number;
  latestEmittedAt: string | null;
}

/** Lowest number = most severe, so the severity sort is a plain ascending compare. */
const SEVERITY_RANK: Record<string, number> = {
  P0: 0,
  P1: 1,
  P2: 2,
  P3: 3,
  P4: 4,
};

/** Null/unknown severity sinks below the explicit ranks. */
function severityRank(severity: string | null): number {
  if (severity == null) return 5;
  return SEVERITY_RANK[severity] ?? 5;
}

/**
 * The most-recently-emitted runs across the fleet, newest first, capped at
 * {@link MAX_FLEET_EMITTED_RUNS}. A run can complete (and emit) later than one
 * started after it, so order by completion and fall back to start time.
 */
export function mostRecentEmittedRuns(runs: ScoutRun[]): ScoutRun[] {
  return runs
    .filter((run) => (run.emitted_count ?? 0) > 0)
    .sort((a, b) =>
      (b.completed_at ?? b.started_at ?? "").localeCompare(
        a.completed_at ?? a.started_at ?? "",
      ),
    )
    .slice(0, MAX_FLEET_EMITTED_RUNS);
}

/**
 * Cheap summary for the fleet callout — derived from the runs window alone, so
 * it never triggers the per-run emissions fetch the findings page does on open.
 */
export function summarizeEmittedRuns(runs: ScoutRun[]): ScoutFindingsSummary {
  const emitted = mostRecentEmittedRuns(runs);
  let totalCount = 0;
  const scouts = new Set<string>();
  let latestEmittedAt: string | null = null;
  for (const run of emitted) {
    totalCount += run.emitted_count ?? 0;
    scouts.add(run.skill_name);
    const at = run.completed_at ?? run.started_at;
    if (at && (!latestEmittedAt || at > latestEmittedAt)) latestEmittedAt = at;
  }
  return { totalCount, scoutCount: scouts.size, latestEmittedAt };
}

/**
 * Join emissions back to their run and the report their signal grouped into.
 * Emissions whose run isn't in the window are dropped (the run set is the source
 * of truth for what's shown). Reports are keyed by `source_id`.
 */
export function buildScoutFindingRows(
  emissions: ScoutEmission[],
  emittedRuns: ScoutRun[],
  reportLinks: ScoutEmissionReportLink[],
): ScoutFindingRow[] {
  const runsById = new Map(emittedRuns.map((run) => [run.run_id, run]));
  const reportBySourceId = new Map<string, LinkedSignalReport>();
  for (const link of reportLinks) {
    if (link.report) reportBySourceId.set(link.source_id, link.report);
  }
  const rows: ScoutFindingRow[] = [];
  for (const emission of emissions) {
    const run = runsById.get(emission.run_id);
    if (!run) continue;
    rows.push({
      emission,
      run,
      linkedReport: reportBySourceId.get(emission.source_id) ?? null,
    });
  }
  return rows;
}

/** Distinct scouts present in the rows, with a per-scout count, for the filter. */
export function availableScoutsFromRows(
  rows: ScoutFindingRow[],
): ScoutFilterOption[] {
  const counts = new Map<string, number>();
  for (const row of rows) {
    counts.set(row.run.skill_name, (counts.get(row.run.skill_name) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([skillName, count]) => ({
      skillName,
      label: prettifyScoutSkillName(skillName),
      count,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

const byNewest = (a: ScoutFindingRow, b: ScoutFindingRow): number =>
  (b.emission.emitted_at ?? "").localeCompare(a.emission.emitted_at ?? "");

/**
 * Visible set: search (over finding text + prettified scout name) + scout +
 * severity, then sort by the chosen key.
 */
export function filterAndSortScoutFindings(
  rows: ScoutFindingRow[],
  filter: ScoutFindingsFilter,
): ScoutFindingRow[] {
  const needle = filter.search.trim().toLowerCase();
  const filtered = rows.filter((row) => {
    if (
      filter.scout !== SCOUT_FINDINGS_SCOUT_FILTER_ALL &&
      row.run.skill_name !== filter.scout
    ) {
      return false;
    }
    if (
      filter.severity !== SCOUT_FINDINGS_SEVERITY_FILTER_ALL &&
      row.emission.severity !== filter.severity
    ) {
      return false;
    }
    if (needle) {
      const haystack =
        `${row.emission.description ?? ""} ${prettifyScoutSkillName(row.run.skill_name)}`.toLowerCase();
      if (!haystack.includes(needle)) return false;
    }
    return true;
  });
  return filtered.sort((a, b) => {
    if (filter.sort === "oldest") return -byNewest(a, b);
    if (filter.sort === "severity") {
      const diff =
        severityRank(a.emission.severity) - severityRank(b.emission.severity);
      return diff !== 0 ? diff : byNewest(a, b);
    }
    if (filter.sort === "confidence") {
      const diff = (b.emission.confidence ?? 0) - (a.emission.confidence ?? 0);
      return diff !== 0 ? diff : byNewest(a, b);
    }
    return byNewest(a, b);
  });
}

/** Header tallies, computed from the joined rows (not the cheap window sum). */
export function summarizeScoutFindingRows(
  rows: ScoutFindingRow[],
): ScoutFindingsSummary {
  const scouts = new Set<string>();
  let latestEmittedAt: string | null = null;
  for (const row of rows) {
    scouts.add(row.run.skill_name);
    const at = row.emission.emitted_at;
    if (at && (!latestEmittedAt || at > latestEmittedAt)) latestEmittedAt = at;
  }
  return {
    totalCount: rows.length,
    scoutCount: scouts.size,
    latestEmittedAt,
  };
}
