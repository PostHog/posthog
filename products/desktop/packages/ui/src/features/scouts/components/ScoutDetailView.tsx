import type { ScoutDetailTab } from "@posthog/core/scouts/scoutDetailTabs";
import {
  computeScoutRollups,
  getScoutOrigin,
  prettifyScoutSkillName,
  scoutSkillNameFromSlug,
} from "@posthog/core/scouts/scoutPresentation";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useAgentsPageActions } from "@posthog/ui/features/agents/agentsPageStore";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useMemo, useRef } from "react";
import { useAuthStateValue } from "../../auth/store";
import { useScoutConfigMutations } from "../hooks/useScoutConfigMutations";
import { useScoutConfigs } from "../hooks/useScoutConfigs";
import { useScoutRuns } from "../hooks/useScoutRuns";
import { ScoutActivityTab } from "./ScoutActivityTab";
import { ScoutConfigForm } from "./ScoutConfigControls";
import { ScoutDetailHeader } from "./ScoutDetailHeader";
import { ScoutOutputSection } from "./ScoutOutputSection";

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
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const skillName = scoutSkillNameFromSlug(skillSlug);
  const displayName = prettifyScoutSkillName(skillName);
  const { showAgentTab, showTab } = useAgentsPageActions();

  const configsQuery = useScoutConfigs();
  const {
    data: configs,
    isLoading: configsLoading,
    isError: configsError,
  } = configsQuery;
  const runsQuery = useScoutRuns(skillName);
  const {
    data: runsWindow,
    isLoading: runsLoading,
    isFetching: runsLoadingMore,
    isError: runsError,
  } = runsQuery;
  const incomplete = runsWindow ? !runsWindow.complete : false;
  const { updateConfig } = useScoutConfigMutations();

  const config = configs?.find((entry) => entry.skill_name === skillName);
  const scoutRuns = useMemo(
    () =>
      (runsWindow?.runs ?? []).filter((run) => run.skill_name === skillName),
    [runsWindow, skillName],
  );
  const rollup = useMemo(
    () => computeScoutRollups(scoutRuns).get(skillName),
    [scoutRuns, skillName],
  );
  // Pages arrive newest first, so an agent with nothing yet may still be in a
  // page that has not landed. That reads as loading, never as "no runs".
  const runsUnknown =
    runsLoading || (runsLoadingMore && scoutRuns.length === 0);

  const showDetailTab = (next: ScoutDetailTab) => {
    track(ANALYTICS_EVENTS.SCOUT_ACTION, {
      action_type: "switch_detail_tab",
      surface: "scout_detail",
      skill_name: skillName,
      filter: next,
    });
    showAgentTab(next);
  };

  // Fire the viewed event once per scout, after both queries settle so the
  // config and run-window stats are real rather than loading-state zeros.
  const viewTrackedFor = useRef<string | null>(null);
  useEffect(() => {
    if (
      !configsQuery.isFetchedAfterMount ||
      configsQuery.isFetching ||
      configsError ||
      !runsQuery.isFetchedAfterMount ||
      runsQuery.isFetching ||
      runsError
    )
      return;
    if (viewTrackedFor.current === `${projectId}:${skillName}`) return;
    viewTrackedFor.current = `${projectId}:${skillName}`;
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
  }, [
    configsQuery.isFetchedAfterMount,
    configsQuery.isFetching,
    configsError,
    runsQuery.isFetchedAfterMount,
    runsQuery.isFetching,
    runsError,
    projectId,
    skillName,
    config,
    rollup,
  ]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ScoutDetailHeader
        config={config}
        configLoading={configsLoading}
        displayName={displayName}
        rollup={rollup}
        onUpdate={updateConfig}
        tab={tab}
        onTabChange={showDetailTab}
        onBack={() => showTab("agents")}
      />

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-[90rem] px-6 py-6">
          {runsError && runsWindow ? (
            <output className="text-(--amber-11) text-[12.5px]">
              Run history could not refresh. Available data remains visible.
            </output>
          ) : null}
          {configsError && !configs ? (
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
              incomplete={incomplete}
              loading={runsUnknown}
              loadingMore={runsLoadingMore}
              error={runsError && !runsWindow}
            />
          ) : tab === "output" ? (
            <ScoutOutputSection
              key={skillName}
              runs={scoutRuns}
              loading={runsLoading}
              loadingMore={runsLoadingMore}
              incomplete={incomplete}
              error={runsError && !runsWindow}
              highlightFindingId={highlightFindingId}
            />
          ) : config ? (
            <ScoutConfigForm config={config} onUpdate={updateConfig} />
          ) : null}
        </div>
      </div>
    </div>
  );
}
