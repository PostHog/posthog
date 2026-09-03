import { RobotIcon } from "@phosphor-icons/react";
import type { ScoutDetailTab } from "@posthog/core/scouts/scoutDetailTabs";
import {
  computeScoutRollups,
  getScoutOrigin,
  prettifyScoutSkillName,
  scoutSkillNameFromSlug,
} from "@posthog/core/scouts/scoutPresentation";
import { SCOUT_RUNS_WINDOW_LABEL } from "@posthog/core/scouts/scoutRunsWindow";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef } from "react";
import { useScoutConfigMutations } from "../hooks/useScoutConfigMutations";
import { useScoutConfigs } from "../hooks/useScoutConfigs";
import { isRunsWindowLoadingMore, useScoutRuns } from "../hooks/useScoutRuns";
import { ScoutActivityTab } from "./ScoutActivityTab";
import { ScoutConfigForm } from "./ScoutConfigControls";
import { ScoutDetailHeader } from "./ScoutDetailHeader";
import { ScoutSignalsSection } from "./ScoutSignalsSection";

export function ScoutDetailView({
  skillSlug,
  highlightFindingId,
  tab,
}: {
  skillSlug: string;
  /** Emission id from a shared finding link – expanded and scrolled to when present. */
  highlightFindingId?: string;
  tab: ScoutDetailTab;
}) {
  const skillName = scoutSkillNameFromSlug(skillSlug);
  const displayName = prettifyScoutSkillName(skillName);
  const navigate = useNavigate();

  const headerContent = useMemo(
    () => (
      <div className="flex w-full min-w-0 items-center gap-2">
        <RobotIcon size={12} className="shrink-0 text-gray-10" />
        <span
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title={displayName}
        >
          {displayName}
        </span>
      </div>
    ),
    [displayName],
  );
  useSetHeaderContent(headerContent);

  const {
    data: configs,
    isLoading: configsLoading,
    isError: configsError,
  } = useScoutConfigs();
  const runsQuery = useScoutRuns();
  const {
    data: runsWindow,
    isLoading: runsLoading,
    isError: runsError,
  } = runsQuery;
  const runsLoadingMore = isRunsWindowLoadingMore(runsQuery);
  const { updateConfig } = useScoutConfigMutations();

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
  const windowLabel = SCOUT_RUNS_WINDOW_LABEL;
  // Pages arrive newest first, so an agent with nothing yet may still be in a
  // page that has not landed. That reads as loading, never as "no runs".
  const runsUnknown =
    runsLoading || (runsLoadingMore && scoutRuns.length === 0);

  const showTab = (next: ScoutDetailTab) => {
    track(ANALYTICS_EVENTS.SCOUT_ACTION, {
      action_type: "switch_detail_tab",
      surface: "scout_detail",
      skill_name: skillName,
      filter: next,
    });
    void navigate({
      to: "/agents/scouts/$skillName",
      params: { skillName: skillSlug },
      search: (previous) => ({ ...previous, tab: next }),
      replace: true,
    });
  };

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
    <div className="flex h-full min-h-0 flex-col">
      <ScoutDetailHeader
        config={config}
        configLoading={configsLoading}
        displayName={displayName}
        rollup={rollup}
        onUpdate={updateConfig}
        tab={tab}
        onTabChange={showTab}
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-[90rem] px-6 py-6">
          {configsError ? (
            <p className="text-(--red-11) text-[12.5px]">
              Couldn&apos;t load this agent&apos;s configuration.
            </p>
          ) : !configsLoading && !config ? (
            <p className="text-[12.5px] text-gray-11">
              No configuration found for this agent on the current project.
            </p>
          ) : tab === "activity" ? (
            <ScoutActivityTab
              skillName={skillName}
              rollup={rollup}
              runs={scoutRuns}
              runsWindow={runsWindow}
              loading={runsUnknown}
              loadingMore={runsLoadingMore}
              error={runsError}
            />
          ) : tab === "signals" ? (
            <ScoutSignalsSection
              runs={scoutRuns}
              windowLabel={windowLabel}
              loading={runsUnknown}
              error={runsError}
              highlightFindingId={highlightFindingId}
              hideTitle
            />
          ) : config ? (
            <ScoutConfigForm config={config} onUpdate={updateConfig} />
          ) : null}
        </div>
      </div>
    </div>
  );
}
