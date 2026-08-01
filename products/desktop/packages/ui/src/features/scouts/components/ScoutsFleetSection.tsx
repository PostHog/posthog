import type { Icon } from "@phosphor-icons/react";
import {
  CaretDownIcon,
  CompassIcon,
  PlusIcon,
  SparkleIcon,
} from "@phosphor-icons/react";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  computeFleetSummary,
  computeScoutRollups,
  getScoutOrigin,
  listScoutCreatorOptions,
  type ScoutCreatorIndex,
  type ScoutCreatorUser,
  scoutCreatorKey,
  sortConfigsForDisplay,
} from "@posthog/core/scouts/scoutPresentation";
import {
  SCOUT_AUTHOR_PROMPT,
  SCOUT_FLEET_OVERVIEW_PROMPT,
  SCOUT_RECENT_SIGNALS_PROMPT,
} from "@posthog/core/scouts/scoutPrompts";
import {
  SCOUT_RUNS_WINDOW_SPAN,
  type ScoutRunsWindow,
  scoutRunsWindowLabel,
} from "@posthog/core/scouts/scoutRunsWindow";
import type { ScoutChatType } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { track } from "@posthog/ui/shell/analytics";
import { Box, Flex, Text } from "@radix-ui/themes";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMeQuery } from "../../auth/useMeQuery";
import { useScoutChatTask } from "../hooks/useScoutChatTask";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { useScoutConfigMutations } from "../hooks/useScoutConfigMutations";
import { useScoutConfigs } from "../hooks/useScoutConfigs";
import { useScoutRuns } from "../hooks/useScoutRuns";
import { useScoutSkillCreators } from "../hooks/useScoutSkillCreators";
import { FleetFindingsCallout } from "./FleetFindingsCallout";
import { FleetMemoryCallout } from "./FleetMemoryCallout";
import { ScoutAlphaBanner } from "./ScoutAlphaBanner";
import { ScoutHelperSkillLinks } from "./ScoutHelperSkillLinks";
import { ScoutRowCard } from "./ScoutRowCard";

const EMPTY_CONFIGS: ScoutConfig[] = [];

/**
 * Expandable scout fleet manager for the agents config page. Collapsed it is
 * a one-line pulse; expanded it lists every scout with inline config controls.
 * Per-scout drill-down (run history, run detail) stays on its own routes.
 */
export function ScoutsFleetSection() {
  const { data: configs, isLoading, isError, refetch } = useScoutConfigs();
  const [expanded, setExpanded] = useState(false);

  const lastRunAt = useMemo(() => {
    let latest: string | null = null;
    for (const config of configs ?? []) {
      if (config.last_run_at && (!latest || config.last_run_at > latest)) {
        latest = config.last_run_at;
      }
    }
    return latest;
  }, [configs]);

  if (isLoading) {
    return (
      <Box className="h-12 w-full animate-pulse rounded-(--radius-2) bg-(--gray-3)" />
    );
  }

  // A failed request must not masquerade as an empty fleet – a missing scope
  // or regional rollout gap would otherwise be indistinguishable from
  // "no scouts yet".
  if (isError) {
    return (
      <Flex
        align="center"
        gap="3"
        className="rounded-(--radius-2) border border-(--red-6) bg-(--red-2) px-4 py-3.5"
      >
        <Text className="flex-1 text-(--red-11) text-[12.5px]">
          Couldn&apos;t load the scout fleet. The scout API may be unavailable
          or this token may lack the <code>signal_scout</code> scope.
        </Text>
        <button
          type="button"
          onClick={() => refetch()}
          className="shrink-0 rounded-(--radius-2) border border-(--red-7) px-2.5 py-1 text-(--red-11) text-[12px] transition-colors hover:bg-(--red-3)"
        >
          Retry
        </button>
      </Flex>
    );
  }

  if (!configs || configs.length === 0) {
    return <ScoutsEmptyState />;
  }

  const enabledCount = configs.filter((config) => config.enabled).length;

  return (
    <Flex direction="column" gap="3">
      <ScoutAlphaBanner />
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-3 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3.5 text-left transition-colors duration-150 hover:border-(--gray-6) hover:bg-(--gray-2)"
      >
        <Flex align="center" gap="3" className="min-w-0">
          <CompassIcon size={20} className="shrink-0 text-(--iris-9)" />
          <Flex direction="column" gap="0" className="min-w-0">
            <Text className="font-medium text-[13px] text-gray-12">
              Scout fleet
            </Text>
            <Text className="text-[12px] text-gray-11 leading-snug">
              {enabledCount} of {configs.length} scouts enabled
              {lastRunAt ? (
                <>
                  {" · last dispatched "}
                  <RelativeTimestamp timestamp={lastRunAt} />
                </>
              ) : null}
            </Text>
          </Flex>
        </Flex>
        <CaretDownIcon
          size={14}
          className={`shrink-0 text-gray-10 transition-transform duration-150 ${
            expanded ? "" : "-rotate-90"
          }`}
        />
      </button>
      {expanded ? <ScoutsFleetList configs={configs} /> : null}
    </Flex>
  );
}

function useTrackFleetViewed(configs: ScoutConfig[]) {
  const tracked = useRef(false);
  useEffect(() => {
    if (tracked.current) return;
    tracked.current = true;
    track(ANALYTICS_EVENTS.SCOUT_FLEET_VIEWED, {
      scout_count: configs.length,
      enabled_count: configs.filter((config) => config.enabled).length,
      dry_run_count: configs.filter((config) => !config.emit).length,
      custom_count: configs.filter(
        (config) => getScoutOrigin(config) === "custom",
      ).length,
      is_empty: configs.length === 0,
    });
  }, [configs]);
}

function ScoutsFleetList({ configs }: { configs: ScoutConfig[] }) {
  const { data: runsWindow } = useScoutRuns();
  const { updateConfig } = useScoutConfigMutations();
  const { data: creators } = useScoutSkillCreators();
  const { data: currentUser } = useMeQuery();
  useTrackFleetViewed(configs);

  return (
    <ScoutsFleetListView
      configs={configs}
      runsWindow={runsWindow}
      creators={creators}
      currentUser={currentUser ?? null}
      onUpdateConfig={updateConfig}
    />
  );
}

/**
 * Pure fleet list: summary line, filters, chat CTAs, and the scout rows. Data
 * and mutations come in as props (Storybook renders this directly — the
 * container's hooks never resolve there).
 */
export function ScoutsFleetListView({
  configs,
  runsWindow,
  creators,
  currentUser,
  onUpdateConfig,
  initialCreatorKey = "",
}: {
  configs: ScoutConfig[];
  runsWindow: ScoutRunsWindow | undefined;
  /** Undefined while loading; null when the skills API is unavailable for the org. */
  creators: ScoutCreatorIndex | null | undefined;
  currentUser: ScoutCreatorUser | null;
  onUpdateConfig: (configId: string, updates: ScoutConfigUpdate) => void;
  /** Start with a creator preselected (Storybook seam). */
  initialCreatorKey?: string;
}) {
  const [hideDisabled, setHideDisabled] = useState(false);
  const [creatorKey, setCreatorKey] = useState(initialCreatorKey);

  const runs = runsWindow?.runs;
  const rollups = useMemo(() => computeScoutRollups(runs ?? []), [runs]);
  const summary = useMemo(
    () => computeFleetSummary(configs, rollups),
    [configs, rollups],
  );
  // Null/undefined creators = the skills API is gated for this org (or still
  // loading), so authorship is unknowable; render no picker instead of an
  // always-empty filter.
  const creatorOptions = useMemo(
    () => (creators ? listScoutCreatorOptions(creators, currentUser) : []),
    [creators, currentUser],
  );
  const selectedCreator = creatorOptions.find(
    (option) => option.key === creatorKey,
  );
  const visibleConfigs = useMemo(() => {
    let sorted = sortConfigsForDisplay(configs);
    if (hideDisabled) {
      sorted = sorted.filter((config) => config.enabled);
    }
    if (creatorKey && creators) {
      sorted = sorted.filter(
        (config) =>
          scoutCreatorKey(creators.get(config.skill_name)) === creatorKey,
      );
    }
    return sorted;
  }, [configs, hideDisabled, creatorKey, creators]);

  return (
    <Flex direction="column" gap="3">
      <Flex align="center" gap="2" wrap="wrap">
        <Text className="text-[12.5px] text-gray-11">
          {summary.runningCount > 0
            ? `${summary.runningCount} running now`
            : "None running now"}
          {summary.successRate !== null
            ? ` · ${Math.round(summary.successRate * 100)}% success`
            : ""}
          {` · ${summary.emittedCount} signal${summary.emittedCount === 1 ? "" : "s"} emitted`}
          {summary.emitRate !== null
            ? ` (${Math.round(summary.emitRate * 100)}%)`
            : ""}
          <span className="text-gray-9">
            {" "}
            · {scoutRunsWindowLabel(runsWindow)}
          </span>
        </Text>
        <span className="flex-1" />
        {creatorOptions.length > 0 ? (
          <Flex align="center" gap="2">
            <Text className="whitespace-nowrap text-[12px] text-gray-10">
              Created by
            </Text>
            <div className="w-44">
              <SettingsOptionSelect
                value={creatorKey}
                options={[
                  { value: "", label: "Any user" },
                  ...creatorOptions.map((option) => ({
                    value: option.key,
                    label: option.label,
                  })),
                ]}
                onValueChange={(next) => {
                  setCreatorKey(next);
                  const option = creatorOptions.find(
                    (candidate) => candidate.key === next,
                  );
                  track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                    action_type: "filter_created_by",
                    surface: "fleet_list",
                    created_by_me: option?.isCurrentUser ?? false,
                    filter_match_count: next
                      ? configs.filter(
                          (config) =>
                            scoutCreatorKey(
                              creators?.get(config.skill_name),
                            ) === next,
                        ).length
                      : undefined,
                  });
                }}
                ariaLabel="Filter scouts by creator"
                placeholder="Any user"
              />
            </div>
          </Flex>
        ) : null}
        <button
          type="button"
          onClick={() => {
            const next = !hideDisabled;
            setHideDisabled(next);
            track(ANALYTICS_EVENTS.SCOUT_ACTION, {
              action_type: "toggle_hide_disabled",
              surface: "fleet_list",
              hide_disabled: next,
            });
          }}
          className="rounded px-1.5 py-0.5 text-[12px] text-gray-10 hover:bg-gray-3 hover:text-gray-12"
        >
          {hideDisabled ? "Show disabled" : "Hide disabled"}
        </button>
      </Flex>

      <Flex align="center" gap="2" wrap="wrap">
        <ScoutChatCta
          label="How is my scout fleet performing?"
          prompt={SCOUT_FLEET_OVERVIEW_PROMPT}
          taskLabel="fleet overview"
          loggerScope="scout-fleet-overview"
          chatType="fleet_overview"
        />
        <ScoutChatCta
          label="What signals were emitted recently?"
          prompt={SCOUT_RECENT_SIGNALS_PROMPT}
          taskLabel="recent signals recap"
          loggerScope="scout-recent-signals"
          chatType="recent_signals"
        />
        <ScoutChatCta
          label="Make a scout"
          prompt={SCOUT_AUTHOR_PROMPT}
          taskLabel="scout authoring"
          loggerScope="scout-author"
          chatType="author_scout"
          icon={PlusIcon}
        />
      </Flex>

      {/* Findings: renders only once scouts have emitted something. */}
      <FleetFindingsCallout />

      {/* Fleet memory: renders only once scouts have written scratchpad notes. */}
      <FleetMemoryCallout />

      {/* Bounded to roughly 10 rows; larger fleets scroll within the section. */}
      <div className="max-h-[710px] overflow-y-auto">
        <Flex direction="column" gap="2">
          {visibleConfigs.length === 0 ? (
            <Text className="px-1 py-2 text-[12.5px] text-gray-10">
              {creatorKey
                ? selectedCreator?.isCurrentUser
                  ? "No scouts created by you match the current filters."
                  : "No scouts created by the selected user match the current filters."
                : "No scouts match the current filters."}
            </Text>
          ) : (
            visibleConfigs.map((config) => (
              <ScoutRowCard
                key={config.id}
                config={config}
                rollup={rollups.get(config.skill_name)}
                onUpdate={onUpdateConfig}
              />
            ))
          )}
        </Flex>
      </div>

      <Flex direction="column" gap="1">
        <Text className="text-[12px] text-gray-10">
          Run counts and emitted totals cover the last {SCOUT_RUNS_WINDOW_SPAN}{" "}
          of fleet runs. New scouts are created as{" "}
          <span className="font-mono text-[11px]">signals-scout-*</span> skills
          in your PostHog project.
        </Text>
        <ScoutHelperSkillLinks surface="fleet_list" />
      </Flex>
    </Flex>
  );
}

/**
 * Suggestion-chip CTA that fires an auto-mode cloud task asking the
 * exploring-signals-scouts skill a templated question, then navigates to it –
 * same one-click shape as the inbox discuss / create-PR flows.
 */
function ScoutChatCta({
  label,
  prompt,
  taskLabel,
  loggerScope,
  chatType,
  icon: IconComponent = SparkleIcon,
}: {
  label: string;
  prompt: string;
  taskLabel: string;
  loggerScope: string;
  chatType: ScoutChatType;
  icon?: Icon;
}) {
  const { runTask, isRunning } = useScoutChatTask({
    prompt,
    taskLabel,
    loggerScope,
    chatType,
    surface: "fleet_list",
  });
  return (
    <button
      type="button"
      onClick={() => void runTask()}
      disabled={isRunning}
      className="flex w-fit items-center gap-1.5 rounded-full border border-border bg-(--color-panel-solid) px-3 py-1 text-[12px] text-gray-11 transition-colors duration-150 hover:border-(--gray-6) hover:bg-(--gray-2) hover:text-gray-12 disabled:cursor-default disabled:opacity-60 disabled:hover:border-border disabled:hover:bg-(--color-panel-solid)"
    >
      <IconComponent size={12} className="text-(--iris-9)" />
      {isRunning ? `Starting ${taskLabel}...` : label}
    </button>
  );
}

function ScoutsEmptyState() {
  useTrackFleetViewed(EMPTY_CONFIGS);
  return (
    <Flex direction="column" gap="3">
      <ScoutAlphaBanner />
      <Flex
        direction="column"
        gap="2"
        align="start"
        className="rounded-(--radius-3) border border-border bg-(--color-panel-solid) px-5 py-5"
      >
        <Flex align="center" gap="2">
          <CompassIcon size={18} className="text-(--iris-9)" />
          <Text className="font-medium text-[13px] text-gray-12">
            No scouts on this project yet
          </Text>
        </Flex>
        <Text className="max-w-2xl text-[12.5px] text-gray-11 leading-snug">
          Scouts are rolling out gradually. Once your project is enrolled, the
          canonical fleet appears here automatically and you can add custom
          scouts by creating{" "}
          <span className="font-mono text-[11px]">signals-scout-*</span> skills
          in PostHog.
        </Text>
        <ScoutHelperSkillLinks surface="empty_state" />
      </Flex>
    </Flex>
  );
}
