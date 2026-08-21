import {
  buildScoutFindingRows,
  mostRecentEmittedRuns,
  type ScoutFindingRow,
} from "@posthog/core/scouts/scoutFindings";
import type { ScoutRunsWindow } from "@posthog/core/scouts/scoutRunsWindow";
import { useMemo } from "react";
import { useScoutEmissionReports } from "./useScoutEmissionReports";
import { useScoutRunEmissions } from "./useScoutRunEmissions";
import { useScoutRuns } from "./useScoutRuns";

export interface ScoutFindingsData {
  rows: ScoutFindingRow[];
  runsWindow: ScoutRunsWindow | undefined;
  /** True once the runs window and (if any) emissions have settled at least once. */
  hasLoadedOnce: boolean;
  /** The runs window load failed — the page has no run set to fetch findings for. */
  runsError: boolean;
  /** The batched emissions fetch (the page's actual content) failed. */
  emissionsError: boolean;
  /** A poll/retry of emissions is in flight while a prior set may still be shown. */
  emissionsFetching: boolean;
  /** Re-run the runs window plus the emissions + report-link batches. */
  refetch: () => void;
}

/**
 * Fleet-wide findings — the cross-troop counterpart of the per-scout view.
 * Reuses the shared {@link useScoutRuns} window, narrows it to recently-emitted
 * runs in core, then fetches their findings + report links in two batched
 * requests and flattens them into one list the page filters/sorts. The runs
 * query is cache-shared with the fleet section, so opening this page never
 * double-fetches the window.
 */
export function useScoutFindings(): ScoutFindingsData {
  const {
    data: runsWindow,
    isLoading: runsLoading,
    isError: runsError,
    refetch: refetchRuns,
  } = useScoutRuns();

  const emittedRuns = useMemo(
    () => mostRecentEmittedRuns(runsWindow?.runs ?? []),
    [runsWindow],
  );
  const runIds = useMemo(
    () => emittedRuns.map((run) => run.run_id),
    [emittedRuns],
  );

  const emissionsQuery = useScoutRunEmissions(runIds);
  const reportsQuery = useScoutEmissionReports(runIds);

  const rows = useMemo(
    () =>
      buildScoutFindingRows(
        emissionsQuery.data ?? [],
        emittedRuns,
        reportsQuery.data ?? [],
      ),
    [emissionsQuery.data, emittedRuns, reportsQuery.data],
  );

  // "Loaded once" distinguishes "not loaded yet" (skeleton) from "loaded, empty".
  // With no emitted runs there's nothing to fetch, so the runs load alone settles
  // it; otherwise wait for the emissions batch to have fetched at least once.
  const hasLoadedOnce =
    !runsLoading && (runIds.length === 0 || emissionsQuery.isFetched);

  return {
    rows,
    runsWindow,
    hasLoadedOnce,
    runsError,
    emissionsError: emissionsQuery.isError,
    emissionsFetching: emissionsQuery.isFetching,
    refetch: () => {
      void refetchRuns();
      void emissionsQuery.refetch();
      void reportsQuery.refetch();
    },
  };
}
