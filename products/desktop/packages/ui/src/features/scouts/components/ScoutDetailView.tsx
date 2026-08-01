import {
  ArrowLeftIcon,
  CaretRightIcon,
  CompassIcon,
} from "@phosphor-icons/react";
import type { ScoutRun } from "@posthog/api-client/posthog-client";
import {
  computeScoutRollups,
  deriveRunFailureKind,
  formatRunDuration,
  getScoutOrigin,
  normalizeRunStatus,
  prettifyScoutSkillName,
  runDurationSeconds,
  runMatchesFilter,
  type ScoutRunFilter,
  scoutSkillNameFromSlug,
} from "@posthog/core/scouts/scoutPresentation";
import {
  SCOUT_RUNS_WINDOW_SPAN,
  scoutRunsWindowLabel,
} from "@posthog/core/scouts/scoutRunsWindow";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { track } from "@posthog/ui/shell/analytics";
import { getPostHogUrl } from "@posthog/ui/utils/urls";
import { Badge, Box, Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { useScoutConfigMutations } from "../hooks/useScoutConfigMutations";
import { useScoutConfigs } from "../hooks/useScoutConfigs";
import { useScoutRuns } from "../hooks/useScoutRuns";
import { ScoutDetailHeader } from "./ScoutDetailHeader";
import { ScoutSignalsSection } from "./ScoutSignalsSection";
import { ScoutTaskRunLink } from "./ScoutTaskRunLink";

const FILTERS: { value: ScoutRunFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "emitted", label: "Emitted" },
  { value: "quiet", label: "Quiet" },
  { value: "failed", label: "Failed" },
];

export function ScoutDetailView({
  skillSlug,
  highlightFindingId,
}: {
  skillSlug: string;
  /** Emission id from a shared finding link – expanded and scrolled to when present. */
  highlightFindingId?: string;
}) {
  const skillName = scoutSkillNameFromSlug(skillSlug);
  const displayName = prettifyScoutSkillName(skillName);

  const headerContent = useMemo(
    () => (
      <Flex align="center" gap="2" className="w-full min-w-0">
        <CompassIcon size={12} className="shrink-0 text-gray-10" />
        <Text
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title={displayName}
        >
          {displayName}
        </Text>
      </Flex>
    ),
    [displayName],
  );
  useSetHeaderContent(headerContent);

  const {
    data: configs,
    isLoading: configsLoading,
    isError: configsError,
  } = useScoutConfigs();
  const {
    data: runsWindow,
    isLoading: runsLoading,
    isError: runsError,
  } = useScoutRuns();
  const { updateConfig } = useScoutConfigMutations();
  const [filter, setFilter] = useState<ScoutRunFilter>("all");

  const config = configs?.find((entry) => entry.skill_name === skillName);
  // The runs endpoint has no skill_name filter yet (scouts-ui api gap 1), so
  // select this scout's runs from the fleet window client-side.
  const scoutRuns = useMemo(
    () =>
      (runsWindow?.runs ?? []).filter((run) => run.skill_name === skillName),
    [runsWindow, skillName],
  );
  const rollup = useMemo(
    () => computeScoutRollups(scoutRuns).get(skillName),
    [scoutRuns, skillName],
  );
  const filteredRuns = useMemo(
    () => scoutRuns.filter((run) => runMatchesFilter(run, filter)),
    [scoutRuns, filter],
  );
  const filterCounts = useMemo(() => {
    const counts = new Map<ScoutRunFilter, number>();
    for (const entry of FILTERS) {
      counts.set(
        entry.value,
        scoutRuns.filter((run) => runMatchesFilter(run, entry.value)).length,
      );
    }
    return counts;
  }, [scoutRuns]);

  // Fire the viewed event once per scout, after both queries settle so the
  // config and run-window stats are real rather than loading-state zeros.
  const viewTrackedFor = useRef<string | null>(null);
  useEffect(() => {
    if (configsLoading || runsLoading) return;
    if (viewTrackedFor.current === skillName) return;
    viewTrackedFor.current = skillName;
    track(ANALYTICS_EVENTS.SCOUT_DETAIL_VIEWED, {
      skill_name: skillName,
      scout_origin: getScoutOrigin(config),
      has_config: Boolean(config),
      enabled: config?.enabled ?? null,
      emit: config?.emit ?? null,
      run_interval_minutes: config?.run_interval_minutes ?? null,
      run_count: rollup?.runCount ?? 0,
      emitted_signal_count: rollup?.emittedCount ?? 0,
      failed_run_count: rollup?.failedCount ?? 0,
    });
  }, [configsLoading, runsLoading, skillName, config, rollup]);

  return (
    <Flex direction="column" className="h-full min-h-0">
      <Flex
        direction="column"
        gap="2"
        className="border-(--gray-5) border-b px-6 pt-5 pb-5"
      >
        <Link
          to="/code/agents"
          className="flex w-fit items-center gap-1 text-[12px] text-gray-10 no-underline hover:text-gray-12"
        >
          <ArrowLeftIcon size={12} />
          Agents
        </Link>
        {configsLoading ? (
          <Box className="h-7 w-64 animate-pulse rounded bg-(--gray-3)" />
        ) : config ? (
          <ScoutDetailHeader
            config={config}
            rollup={rollup}
            onUpdate={updateConfig}
            windowLabel={scoutRunsWindowLabel(runsWindow)}
            displayName={displayName}
            runsLoading={runsLoading}
          />
        ) : (
          <Text className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
            {displayName}
          </Text>
        )}
      </Flex>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-4xl px-6 py-6">
          <Flex direction="column" gap="5">
            {configsError ? (
              <Text className="text-(--red-11) text-[12.5px]">
                Couldn&apos;t load this scout&apos;s config.
              </Text>
            ) : !configsLoading && !config ? (
              <Text className="text-[12.5px] text-gray-11">
                No config found for this scout on the current project.
              </Text>
            ) : config?.description?.trim() ? (
              <Text className="text-pretty text-[12.5px] text-gray-11 leading-relaxed">
                {config.description.trim()}
              </Text>
            ) : null}

            <ScoutSignalsSection
              runs={scoutRuns}
              windowLabel={scoutRunsWindowLabel(runsWindow)}
              loading={runsLoading}
              error={runsError}
              highlightFindingId={highlightFindingId}
            />

            <Flex direction="column" gap="3">
              <Flex align="center" gap="2" wrap="wrap">
                <Text className="font-semibold text-[13px] text-gray-12">
                  Runs
                </Text>
                <span className="flex-1" />
                {FILTERS.map((entry) => (
                  <button
                    key={entry.value}
                    type="button"
                    onClick={() => {
                      setFilter(entry.value);
                      track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                        action_type: "filter_runs",
                        surface: "scout_detail",
                        skill_name: skillName,
                        filter: entry.value,
                        filter_match_count: filterCounts.get(entry.value) ?? 0,
                      });
                    }}
                    className={`rounded-full px-2.5 py-0.5 text-[11.5px] transition-colors ${
                      filter === entry.value
                        ? "bg-(--accent-4) text-accent-12"
                        : "text-gray-10 hover:bg-gray-3 hover:text-gray-12"
                    }`}
                  >
                    {entry.label} {filterCounts.get(entry.value) ?? 0}
                  </button>
                ))}
              </Flex>

              {runsLoading ? (
                <RunListSkeleton />
              ) : runsError ? (
                <Text className="text-(--red-11) text-[12.5px]">
                  Couldn&apos;t load runs for this scout. The scout API may be
                  unavailable or this token may lack the{" "}
                  <code>signal_scout</code> scope.
                </Text>
              ) : filteredRuns.length === 0 ? (
                <Text className="text-[12.5px] text-gray-11">
                  {scoutRuns.length > 0
                    ? `No runs match this filter in the ${scoutRunsWindowLabel(runsWindow)}.`
                    : runsWindow && !runsWindow.complete
                      ? `No runs fetched in the last ${SCOUT_RUNS_WINDOW_SPAN} – the fleet window was truncated before it could cover this scout, so runs may exist beyond what was fetched.`
                      : `No runs in the ${scoutRunsWindowLabel(runsWindow)}.`}
                </Text>
              ) : (
                <Flex direction="column" gap="2">
                  {filteredRuns.map((run) => (
                    <ScoutRunListItem key={run.run_id} run={run} />
                  ))}
                </Flex>
              )}

              <Text className="text-[12px] text-gray-10">
                Showing this scout&apos;s runs from the last{" "}
                {SCOUT_RUNS_WINDOW_SPAN}.
              </Text>
            </Flex>
          </Flex>
        </div>
      </div>
    </Flex>
  );
}

function ScoutRunListItem({ run }: { run: ScoutRun }) {
  const [expanded, setExpanded] = useState(false);
  const taskRunUrl = run.task_url ? getPostHogUrl(run.task_url) : null;
  const now = new Date();
  const status = normalizeRunStatus(run.status);
  const failureKind = deriveRunFailureKind(run, now);
  const duration = formatRunDuration(runDurationSeconds(run, now));
  const emitted = run.emitted_count ?? 0;

  return (
    <Box className="rounded-(--radius-3) border border-border bg-(--color-panel-solid) px-4 py-3 transition duration-150 hover:border-(--gray-6)">
      <button
        type="button"
        onClick={() => {
          const next = !expanded;
          setExpanded(next);
          track(ANALYTICS_EVENTS.SCOUT_ACTION, {
            action_type: next ? "expand_run" : "collapse_run",
            surface: "scout_detail",
            skill_name: run.skill_name,
            run_id: run.run_id,
            run_status: status,
            emitted_count: emitted,
          });
        }}
        aria-expanded={expanded}
        className="flex w-full select-none items-center gap-2 text-left"
      >
        <CaretRightIcon
          size={11}
          className={`shrink-0 text-gray-9 transition-transform duration-150 ${expanded ? "rotate-90" : ""}`}
        />
        <RunGlyph status={status} emitted={emitted} />
        <RelativeTimestamp timestamp={run.started_at} />
        {duration ? (
          <Text className="text-[11.5px] text-gray-10">· {duration}</Text>
        ) : null}
        {failureKind ? (
          <Text className="text-(--amber-11) text-[11.5px]">
            · {failureKind === "timed_out" ? "timed out" : "failed"}
          </Text>
        ) : null}
        <span className="flex-1" />
        {emitted > 0 ? (
          <Badge variant="soft" color="iris" size="1" className="text-[11px]">
            {emitted} signal{emitted === 1 ? "" : "s"} emitted
          </Badge>
        ) : status === "completed" ? (
          <Text className="text-[11.5px] text-gray-9">0 signals emitted</Text>
        ) : null}
      </button>
      {run.summary ? (
        <Box
          className={`mt-1.5 text-pretty break-words text-[12.5px] text-gray-11 leading-snug [&_code]:text-[11px] [&_p:last-child]:mb-0 [&_p]:mb-1 [&_pre]:text-[11px] ${
            expanded ? "" : "line-clamp-2"
          }`}
        >
          <MarkdownRenderer content={run.summary} />
        </Box>
      ) : status === "failed" ? (
        <Text className="mt-1.5 block text-[12.5px] text-gray-10 italic leading-snug">
          No summary – the run ended before writing its close-out. The task run
          in PostHog is the only diagnostic.
        </Text>
      ) : null}
      {expanded ? (
        <Flex
          align="center"
          gap="2"
          mt="2"
          pt="2"
          className="border-t border-t-(--gray-5) text-[11px] text-gray-10"
        >
          <Text className="font-mono text-[11px]">{run.run_id}</Text>
          <span className="flex-1" />
          {taskRunUrl ? (
            <ScoutTaskRunLink
              run={run}
              taskRunUrl={taskRunUrl}
              runStatus={status}
            />
          ) : (
            <Text className="shrink-0 text-[11px] text-gray-9">
              No task link available
            </Text>
          )}
        </Flex>
      ) : null}
    </Box>
  );
}

function RunGlyph({ status, emitted }: { status: string; emitted: number }) {
  if (status === "failed") {
    return <Text className="font-medium text-(--red-9) text-[12px]">✗</Text>;
  }
  if (status === "running" || status === "queued") {
    return (
      <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-(--blue-9)" />
    );
  }
  if (emitted > 0) {
    return <Text className="font-medium text-(--iris-9) text-[12px]">◆</Text>;
  }
  return <Text className="text-[12px] text-gray-8">·</Text>;
}

function RunListSkeleton() {
  return (
    <Flex direction="column" gap="2">
      {[0, 1, 2].map((index) => (
        <Box
          key={index}
          className="h-14 w-full animate-pulse rounded-(--radius-3) bg-(--gray-3)"
        />
      ))}
    </Flex>
  );
}
