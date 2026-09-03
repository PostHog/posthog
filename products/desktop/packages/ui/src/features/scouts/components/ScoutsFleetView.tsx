import { CheckIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  computeFleetSummary,
  computeScoutRollups,
  deriveScoutLifecycle,
  getScoutOrigin,
  listScoutCreatorOptions,
  listScoutsNeedingAttention,
  prettifyScoutSkillName,
  type ScoutOrigin,
  scoutCreatorKey,
  sortConfigsForDisplay,
} from "@posthog/core/scouts/scoutPresentation";
import { SCOUT_RUNS_WINDOW_LABEL } from "@posthog/core/scouts/scoutRunsWindow";
import {
  Button,
  Input,
  Skeleton,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { track } from "@posthog/ui/shell/analytics";
import { useMemo, useState } from "react";
import { useMeQuery } from "../../auth/useMeQuery";
import { useScoutConfigMutations } from "../hooks/useScoutConfigMutations";
import { useScoutConfigs } from "../hooks/useScoutConfigs";
import { useScoutFleetSync } from "../hooks/useScoutFleetSync";
import { useScoutRuns } from "../hooks/useScoutRuns";
import { useScoutSkillCreators } from "../hooks/useScoutSkillCreators";
import { useTrackFleetViewed } from "../hooks/useTrackFleetViewed";
import { ScoutAttentionStrip } from "./ScoutAttentionStrip";
import { ScoutsEmptyState } from "./ScoutsEmptyState";
import { ScoutTable } from "./ScoutTable";

const EMPTY_CONFIGS: ScoutConfig[] = [];

type OriginFilter = ScoutOrigin | "all";

const ORIGIN_TABS: { value: OriginFilter; label: string }[] = [
  { value: "custom", label: "Custom" },
  { value: "canonical", label: "Built-in" },
  { value: "all", label: "All" },
];

/** The fleet index: what needs a decision, then every agent in a table. */
export function ScoutsFleetView({ onNewAgent }: { onNewAgent: () => void }) {
  const { data: configs, isLoading, isError, refetch } = useScoutConfigs();
  // Opening this page is what materializes the fleet, so a project the
  // coordinator never reached still gets its scouts.
  const { isSyncing, syncOutcome } = useScoutFleetSync();
  const { data: runsWindow } = useScoutRuns();
  const { data: creators } = useScoutSkillCreators();
  const { data: currentUser } = useMeQuery();
  const { updateConfig } = useScoutConfigMutations();
  useTrackFleetViewed(configs ?? EMPTY_CONFIGS, syncOutcome);

  const [originChoice, setOriginChoice] = useState<OriginFilter | null>(null);
  const [search, setSearch] = useState("");
  const [creatorKey, setCreatorKey] = useState("");
  const [hideDisabled, setHideDisabled] = useState(false);

  const rollups = useMemo(
    () => computeScoutRollups(runsWindow?.runs ?? []),
    [runsWindow],
  );
  const summary = useMemo(
    () => computeFleetSummary(configs ?? EMPTY_CONFIGS, rollups),
    [configs, rollups],
  );
  const attention = useMemo(
    () =>
      listScoutsNeedingAttention(configs ?? EMPTY_CONFIGS, rollups, new Date()),
    [configs, rollups],
  );
  const originCounts = useMemo(() => {
    const counts: Record<OriginFilter, number> = {
      custom: 0,
      canonical: 0,
      all: 0,
    };
    for (const config of configs ?? EMPTY_CONFIGS) {
      counts[getScoutOrigin(config)] += 1;
      counts.all += 1;
    }
    return counts;
  }, [configs]);
  // Custom agents are the ones a person wrote, so they lead when there are any.
  const origin: OriginFilter =
    originChoice ?? (originCounts.custom > 0 ? "custom" : "all");

  const creatorOptions = useMemo(
    () => (creators ? listScoutCreatorOptions(creators, currentUser) : []),
    [creators, currentUser],
  );

  const visibleConfigs = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const urgent = new Set(attention.map((item) => item.config.id));
    const sorted = sortConfigsForDisplay(configs ?? EMPTY_CONFIGS).sort(
      (a, b) => Number(urgent.has(b.id)) - Number(urgent.has(a.id)),
    );
    return sorted.filter((config) => {
      if (origin !== "all" && getScoutOrigin(config) !== origin) return false;
      if (
        hideDisabled &&
        !config.enabled &&
        !deriveScoutLifecycle(config).isSystemPaused
      ) {
        return false;
      }
      if (
        creatorKey &&
        creators &&
        scoutCreatorKey(creators.get(config.skill_name)) !== creatorKey
      ) {
        return false;
      }
      if (!needle) return true;
      return (
        prettifyScoutSkillName(config.skill_name)
          .toLowerCase()
          .includes(needle) ||
        (config.description ?? "").toLowerCase().includes(needle)
      );
    });
  }, [configs, origin, hideDisabled, creatorKey, creators, search, attention]);

  if (isLoading || (isSyncing && !configs?.length)) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-5 w-96" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center gap-3 rounded-(--radius-md) border border-(--red-6) bg-(--red-2) px-4 py-3.5">
        <p className="flex-1 text-(--red-11) text-[12.5px]">
          Couldn&apos;t load your agents. The agent API may be unavailable or
          this token may lack the <code>signal_scout</code> scope.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => refetch()}
        >
          Retry
        </Button>
      </div>
    );
  }

  if (!configs || configs.length === 0) {
    return <ScoutsEmptyState onNewAgent={onNewAgent} />;
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="flex flex-wrap items-center gap-x-1.5 text-[12.5px] text-gray-10">
        <span>
          <Stat value={summary.enabledCount} /> of {summary.totalCount} enabled
        </span>
        {summary.runningCount > 0 ? (
          <>
            <Dot />
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-(--blue-9)" />
              <Stat value={summary.runningCount} /> running now
            </span>
          </>
        ) : null}
        {summary.successRate !== null ? (
          <>
            <Dot />
            <span>
              <Stat value={`${Math.round(summary.successRate * 100)}%`} />{" "}
              success
            </span>
          </>
        ) : null}
        <Dot />
        <span>
          <Stat value={summary.emittedCount} /> signal
          {summary.emittedCount === 1 ? "" : "s"}
        </span>
        <Dot />
        <span>{SCOUT_RUNS_WINDOW_LABEL}</span>
        <span className="flex-1" />
        {summary.systemPausedCount > 0 ? (
          <span className="text-(--amber-11)">
            {summary.systemPausedCount} auto-paused
          </span>
        ) : null}
        {summary.pausingSoonCount > 0 ? (
          <span className="text-(--amber-11)">
            {summary.systemPausedCount > 0 ? " · " : ""}
            {summary.pausingSoonCount} pausing soon
          </span>
        ) : null}
      </p>

      {attention.length > 0 ? (
        <ScoutAttentionStrip items={attention} onUpdateConfig={updateConfig} />
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Tabs
          value={origin}
          onValueChange={(value: string) => {
            setOriginChoice(value as OriginFilter);
            track(ANALYTICS_EVENTS.SCOUT_ACTION, {
              action_type: "filter_origin",
              surface: "fleet_list",
              filter: value,
            });
          }}
        >
          <TabsList className="h-8">
            {ORIGIN_TABS.map(({ value, label }) => (
              <TabsTrigger key={value} value={value} className="gap-1.5 px-2.5">
                {label}
                <span className="text-[11px] text-gray-10 tabular-nums">
                  {originCounts[value]}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="relative w-52">
          <MagnifyingGlassIcon
            size={13}
            className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-2.5 text-gray-10"
          />
          <Input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onBlur={() => {
              if (search.trim()) {
                track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                  action_type: "search_agents",
                  surface: "fleet_list",
                  filter_match_count: visibleConfigs.length,
                });
              }
            }}
            placeholder="Search agents"
            aria-label="Search agents"
            className="h-8 pl-7"
          />
        </div>
        {creatorOptions.length > 0 ? (
          <div className="w-44">
            <SettingsOptionSelect
              value={creatorKey}
              options={[
                { value: "", label: "Created by anyone" },
                ...creatorOptions.map((option) => ({
                  value: option.key,
                  label: option.label,
                })),
              ]}
              onValueChange={(next) => {
                setCreatorKey(next);
                track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                  action_type: "filter_created_by",
                  surface: "fleet_list",
                  created_by_me:
                    creatorOptions.find((option) => option.key === next)
                      ?.isCurrentUser ?? false,
                });
              }}
              ariaLabel="Filter agents by creator"
              placeholder="Created by anyone"
            />
          </div>
        ) : null}
        <Button
          type="button"
          variant={hideDisabled ? "outline" : "link-muted"}
          size="sm"
          onClick={() => {
            const next = !hideDisabled;
            setHideDisabled(next);
            track(ANALYTICS_EVENTS.SCOUT_ACTION, {
              action_type: "toggle_hide_disabled",
              surface: "fleet_list",
              hide_disabled: next,
            });
          }}
        >
          {hideDisabled ? <CheckIcon size={12} /> : null}
          Hide disabled
        </Button>
      </div>

      <ScoutTable
        configs={visibleConfigs}
        rollups={rollups}
        creators={creators}
        onUpdateConfig={updateConfig}
        emptyMessage={
          search.trim()
            ? "No agents match your search."
            : "No agents match the current filters."
        }
      />

      <p className="flex flex-wrap items-center gap-x-1.5 text-[12px] text-gray-10">
        <span className="flex items-center gap-3">
          <Legend className="bg-(--iris-9)" label="signal" />
          <Legend className="bg-(--gray-6)" label="quiet" />
          <Legend className="bg-(--red-9)" label="failed" />
        </span>
        <span className="text-gray-8">·</span>
        Showing {visibleConfigs.length} of {configs.length} agents. Run history
        covers the {SCOUT_RUNS_WINDOW_LABEL}.
        {runsWindow && !runsWindow.complete
          ? " Some runs in this window did not load."
          : ""}{" "}
        Built-in agents are PostHog&apos;s own. You can switch them on or off
        but not edit them.
      </p>
    </div>
  );
}

function Stat({ value }: { value: number | string }) {
  return <span className="font-medium text-gray-12 tabular-nums">{value}</span>;
}

function Dot() {
  return <span className="text-gray-8">·</span>;
}

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <i className={`inline-block h-2.5 w-1.5 rounded-[1.5px] ${className}`} />
      {label}
    </span>
  );
}
