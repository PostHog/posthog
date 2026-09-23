import type {
  LinkedSignalReport,
  ScoutEmission,
  ScoutRun,
} from "@posthog/api-client/posthog-client";
import { scoutRunOutputCount } from "@posthog/core/scouts/scoutPresentation";
import { SCOUT_RUNS_WINDOW_LABEL } from "@posthog/core/scouts/scoutRunsWindow";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { track } from "@posthog/ui/shell/analytics";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { useMemo, useState } from "react";
import { useScoutEmissionReports } from "../hooks/useScoutEmissionReports";
import { useScoutRunEmissions } from "../hooks/useScoutRunEmissions";
import { ScoutEmissionCard } from "./ScoutEmissionCard";
import { ScoutFindingDiscussButton } from "./ScoutFindingDiscussButton";
import { ScoutFindingShareButton } from "./ScoutFindingShareButton";
import { ScoutRunReportLinks } from "./ScoutRunReportLinks";
import { ScoutTaskRunLink } from "./ScoutTaskRunLink";

/**
 * Cadence bounds a scout to ~48 runs per window (30-minute minimum interval),
 * but a backend-configured cadence below the UI presets could push past that;
 * capping the initially shown runs keeps the batched emissions request small.
 */
const INITIAL_EMITTED_RUNS = 10;

/**
 * Report ids are on the run itself. Only legacy findings need the emissions
 * and reverse-report lookup requests.
 */
export function ScoutOutputSection({
  runs,
  loading,
  loadingMore = false,
  incomplete = false,
  error,
  highlightFindingId,
}: {
  runs: ScoutRun[];
  loading: boolean;
  loadingMore?: boolean;
  incomplete?: boolean;
  error?: boolean;
  /** Emission id from a shared finding link – expanded and scrolled to when present. */
  highlightFindingId?: string;
}) {
  const [showAll, setShowAll] = useState(false);
  const emittedRuns = useMemo(
    () => runs.filter((run) => scoutRunOutputCount(run) > 0),
    [runs],
  );
  const visibleRuns = useMemo(
    () => (showAll ? emittedRuns : emittedRuns.slice(0, INITIAL_EMITTED_RUNS)),
    [emittedRuns, showAll],
  );
  const hiddenCount = emittedRuns.length - visibleRuns.length;
  const visibleRunIds = useMemo(
    () =>
      visibleRuns
        .filter((run) => (run.emitted_count ?? 0) > 0)
        .map((run) => run.run_id),
    [visibleRuns],
  );

  const {
    data: emissions,
    isLoading: emissionsLoading,
    isError: emissionsError,
  } = useScoutRunEmissions(visibleRunIds);
  // Best-effort reverse lookup of which inbox report each finding grouped into.
  // A failure here is non-fatal: the cards still render, just without the chip.
  const { data: emissionReports } = useScoutEmissionReports(visibleRunIds);

  const emissionsByRunId = useMemo(() => {
    const map = new Map<string, ScoutEmission[]>();
    for (const emission of emissions ?? []) {
      const list = map.get(emission.run_id);
      if (list) list.push(emission);
      else map.set(emission.run_id, [emission]);
    }
    return map;
  }, [emissions]);

  const reportBySourceId = useMemo(() => {
    const map = new Map<string, LinkedSignalReport>();
    for (const link of emissionReports ?? []) {
      if (link.report) map.set(link.source_id, link.report);
    }
    return map;
  }, [emissionReports]);

  return (
    <div className="flex flex-col gap-3">
      {loadingMore || incomplete ? (
        <output className="text-[12.5px] text-gray-11">
          {loadingMore
            ? "Loading more runs. More output can appear."
            : "The run history is incomplete. More output can exist."}
        </output>
      ) : null}
      {loading ? (
        <div className="h-24 w-full animate-pulse rounded-(--radius-2) bg-(--gray-3)" />
      ) : error ? (
        <p className="text-(--red-11) text-[12.5px]">
          Couldn&apos;t load this agent&apos;s runs, so output for the{" "}
          {SCOUT_RUNS_WINDOW_LABEL} are unavailable.
        </p>
      ) : emittedRuns.length === 0 ? (
        <p className="text-[12.5px] text-gray-11">
          {loadingMore
            ? "Loading output."
            : incomplete
              ? "No output loaded from the available runs."
              : `No output in the ${SCOUT_RUNS_WINDOW_LABEL}. Use Run now to check the agent.`}
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {visibleRuns.map((run) => (
            <div
              key={run.run_id}
              className="flex flex-col gap-2 rounded-(--radius-md) border border-border p-3"
            >
              <RelativeTimestamp
                timestamp={run.completed_at ?? run.started_at}
                className="text-[12px] text-gray-10"
              />
              <ScoutRunReportLinks run={run} />
              {(run.emitted_count ?? 0) > 0 ? (
                <RunEmissions
                  run={run}
                  emissions={emissionsByRunId.get(run.run_id)}
                  reportBySourceId={reportBySourceId}
                  loading={emissionsLoading}
                  error={emissionsError}
                  highlightFindingId={highlightFindingId}
                />
              ) : null}
            </div>
          ))}
          {hiddenCount > 0 ? (
            <button
              type="button"
              onClick={() => {
                setShowAll(true);
                track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                  action_type: "show_more_emitted_runs",
                  surface: "scout_detail",
                  skill_name: runs[0]?.skill_name,
                  emitted_count: emittedRuns.length,
                });
              }}
              className="w-fit rounded-full px-2.5 py-0.5 text-[11.5px] text-gray-10 transition-colors hover:bg-gray-3 hover:text-gray-12"
            >
              Show {hiddenCount} more run{hiddenCount === 1 ? "" : "s"} with
              output
            </button>
          ) : null}
        </div>
      )}
    </div>
  );
}

function RunEmissions({
  run,
  emissions,
  reportBySourceId,
  loading,
  error,
  highlightFindingId,
}: {
  run: ScoutRun;
  emissions: ScoutEmission[] | undefined;
  reportBySourceId: Map<string, LinkedSignalReport>;
  loading: boolean;
  error: boolean;
  highlightFindingId?: string;
}) {
  const taskRunUrl = run.task_url ? getPostHogUrl(run.task_url) : null;

  if (loading) {
    return (
      <div className="h-24 w-full animate-pulse rounded-(--radius-2) bg-(--gray-3)" />
    );
  }

  // The run-level emitted_count promised signals; an errored or empty
  // emissions response must say so rather than render nothing.
  if (error || !emissions || emissions.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3">
        <p className="flex-1 text-[12.5px] text-gray-10">
          {error
            ? "Couldn't load this run's signals."
            : "No signal details available for this run."}
        </p>
        {taskRunUrl ? (
          <ScoutTaskRunLink run={run} taskRunUrl={taskRunUrl} />
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {emissions.map((emission) => (
        <ScoutEmissionCard
          key={emission.id}
          emission={emission}
          skillName={run.skill_name}
          linkedReport={reportBySourceId.get(emission.source_id)}
          highlighted={emission.id === highlightFindingId}
          actions={
            <>
              <ScoutFindingDiscussButton
                emission={emission}
                skillName={run.skill_name}
              />
              <ScoutFindingShareButton
                emission={emission}
                skillName={run.skill_name}
              />
            </>
          }
          footerEnd={
            taskRunUrl ? (
              <ScoutTaskRunLink run={run} taskRunUrl={taskRunUrl} />
            ) : undefined
          }
        />
      ))}
    </div>
  );
}
