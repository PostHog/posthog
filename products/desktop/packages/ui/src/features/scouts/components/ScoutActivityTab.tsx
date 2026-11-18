import type { ScoutRun } from "@posthog/api-client/posthog-client";
import {
  runMatchesFilter,
  type ScoutRollup,
  type ScoutRunFilter,
  summarizeRunWindow,
} from "@posthog/core/scouts/scoutPresentation";
import { SCOUT_RUNS_WINDOW_LABEL } from "@posthog/core/scouts/scoutRunsWindow";
import { Skeleton, Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useMinuteNow } from "@posthog/ui/hooks/useMinuteNow";
import { track } from "@posthog/ui/shell/analytics";
import { useMemo, useState } from "react";
import { ScoutRunBoxes } from "./ScoutRunBoxes";
import { ScoutRunsList } from "./ScoutRunsList";

const FILTERS: { value: ScoutRunFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "emitted", label: "Output" },
  { value: "quiet", label: "Quiet" },
  { value: "failed", label: "Failed" },
];

/** Filters only earn their row once the list is long enough to need them. */
const FILTERS_FROM = 6;

/** Every run in the window, newest first, with one line that sums them up. */
export function ScoutActivityTab({
  skillName,
  rollup,
  runs,
  incomplete,
  loading,
  loadingMore,
  error,
}: {
  skillName: string;
  rollup: ScoutRollup | undefined;
  runs: ScoutRun[];
  incomplete: boolean;
  loading: boolean;
  /** More pages of the run window are still on their way. */
  loadingMore: boolean;
  error: boolean;
}) {
  const [filter, setFilter] = useState<ScoutRunFilter>("all");
  const now = useMinuteNow();
  const sorted = useMemo(
    () =>
      [...runs].sort((a, b) =>
        (b.started_at ?? "").localeCompare(a.started_at ?? ""),
      ),
    [runs],
  );
  const filtered = useMemo(
    () => sorted.filter((run) => runMatchesFilter(run, filter)),
    [sorted, filter],
  );
  const counts = useMemo(() => {
    const map = new Map<ScoutRunFilter, number>();
    for (const entry of FILTERS) {
      map.set(
        entry.value,
        runs.filter((run) => runMatchesFilter(run, entry.value)).length,
      );
    }
    return map;
  }, [runs]);
  const summary = useMemo(() => summarizeRunWindow(rollup, now), [rollup, now]);

  return (
    <div className="flex flex-col gap-4">
      {loading ? (
        <Skeleton className="h-5 w-96" />
      ) : (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {rollup && rollup.runs.length > 0 ? (
            <ScoutRunBoxes runs={rollup.runs} />
          ) : null}
          <span className="text-[12.5px] text-gray-12">
            {summary ??
              (error
                ? "Run history is unavailable."
                : loadingMore
                  ? "Loading runs."
                  : incomplete
                    ? "No runs loaded. The run history is incomplete."
                    : `No runs in the ${SCOUT_RUNS_WINDOW_LABEL}.`)}
          </span>
          <span className="flex-1" />
          <span className="text-[11.5px] text-gray-10">
            {loadingMore
              ? `${capitalize(SCOUT_RUNS_WINDOW_LABEL)} · loading more runs`
              : incomplete
                ? `${capitalize(SCOUT_RUNS_WINDOW_LABEL)}. Some runs in this window did not load.`
                : capitalize(SCOUT_RUNS_WINDOW_LABEL)}
          </span>
        </div>
      )}

      {runs.length >= FILTERS_FROM || filter !== "all" ? (
        <Tabs
          value={filter}
          onValueChange={(value: string) => {
            const next = value as ScoutRunFilter;
            setFilter(next);
            track(ANALYTICS_EVENTS.SCOUT_ACTION, {
              action_type: "filter_runs",
              surface: "scout_detail",
              skill_name: skillName,
              filter: next,
              filter_match_count: counts.get(next) ?? 0,
            });
          }}
        >
          <TabsList className="h-8">
            {FILTERS.map((entry) => {
              const count = counts.get(entry.value) ?? 0;
              if (
                entry.value !== "all" &&
                entry.value !== filter &&
                count === 0
              )
                return null;
              return (
                <TabsTrigger
                  key={entry.value}
                  value={entry.value}
                  className="gap-1.5 px-2.5"
                >
                  {entry.label}
                  <span className="text-[11px] text-gray-10 tabular-nums">
                    {count}
                  </span>
                </TabsTrigger>
              );
            })}
          </TabsList>
        </Tabs>
      ) : null}

      <ScoutRunsList
        runs={filtered}
        loading={loading}
        error={error}
        emptyMessage={
          runs.length > 0
            ? `No runs match this filter in the ${SCOUT_RUNS_WINDOW_LABEL}.`
            : incomplete
              ? `No runs loaded for the ${SCOUT_RUNS_WINDOW_LABEL}. Runs may exist beyond what was fetched.`
              : `No runs in the ${SCOUT_RUNS_WINDOW_LABEL}. Use Run now to start one.`
        }
      />
    </div>
  );
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
