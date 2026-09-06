import type {
  ScoutRun,
  ScoutRunsQueryParams,
} from "@posthog/api-client/posthog-client";

/**
 * The fleet run window every scout stat describes. The backend caps each
 * runs-list response at 100 rows, so covering a fixed time window means
 * walking `date_to` back page by page (the endpoint documents this cursor
 * pattern). A fixed window gives users a stable frame for every number;
 * "the most recent 100 runs" does not.
 */
export const SCOUT_RUNS_WINDOW_HOURS = 72;

/**
 * Human-friendly span the window covers, e.g. "3 days" or "24h". Reads as days
 * when the window is a whole number of days, otherwise falls back to hours.
 */
export const SCOUT_RUNS_WINDOW_SPAN = (() => {
  if (SCOUT_RUNS_WINDOW_HOURS % 24 !== 0) return `${SCOUT_RUNS_WINDOW_HOURS}h`;
  const days = SCOUT_RUNS_WINDOW_HOURS / 24;
  return `${days} day${days === 1 ? "" : "s"}`;
})();

const PAGE_LIMIT = 100;
const MAX_PAGES = 10;

export interface ScoutRunsClient {
  listScoutRuns(
    projectId: number,
    params?: ScoutRunsQueryParams,
  ): Promise<ScoutRun[]>;
}

export interface ScoutRunsWindow {
  /** Newest-first runs created within the window. */
  runs: ScoutRun[];
  /** False when pagination stopped (page cap or stuck cursor) before reaching the window start. */
  complete: boolean;
}

/** The window as a span, e.g. "last 3 days", with no completeness suffix. */
export const SCOUT_RUNS_WINDOW_LABEL = `last ${SCOUT_RUNS_WINDOW_SPAN}`;

/** Label for stats derived from a window, e.g. "last 3 days". */
export function scoutRunsWindowLabel(window?: ScoutRunsWindow): string {
  const base = `last ${SCOUT_RUNS_WINDOW_SPAN}`;
  return window && !window.complete ? `${base} · truncated` : base;
}

export async function fetchScoutRunsWindow(
  client: ScoutRunsClient,
  projectId: number,
  now: Date = new Date(),
  /** Called with the runs collected so far after each page, newest page first. */
  onPage?: (partial: ScoutRunsWindow) => void,
  skillName?: string,
): Promise<ScoutRunsWindow> {
  const dateFrom = new Date(
    now.getTime() - SCOUT_RUNS_WINDOW_HOURS * 60 * 60 * 1000,
  ).toISOString();

  const runsById = new Map<string, ScoutRun>();
  let dateTo: string | undefined;

  for (let page = 0; page < MAX_PAGES; page++) {
    const batch = await client.listScoutRuns(projectId, {
      skill_name: skillName,
      date_from: dateFrom,
      date_to: dateTo,
      limit: PAGE_LIMIT,
    });

    let added = 0;
    let oldestCreatedAt: string | undefined;
    for (const run of batch) {
      if (!runsById.has(run.run_id)) {
        runsById.set(run.run_id, run);
        added++;
      }
      if (
        run.created_at &&
        (!oldestCreatedAt || run.created_at < oldestCreatedAt)
      ) {
        oldestCreatedAt = run.created_at;
      }
    }

    if (batch.length < PAGE_LIMIT) {
      return { runs: [...runsById.values()], complete: true };
    }
    if (added === 0 || !oldestCreatedAt || oldestCreatedAt === dateTo) {
      // Cursor cannot move: either pure duplicates or runs without created_at.
      return { runs: [...runsById.values()], complete: false };
    }
    dateTo = oldestCreatedAt;
    onPage?.({ runs: [...runsById.values()], complete: false });
  }

  return { runs: [...runsById.values()], complete: false };
}
