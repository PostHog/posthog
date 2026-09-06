import { CheckIcon } from "@phosphor-icons/react";
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
import { suggestionBrief } from "@posthog/core/scouts/scoutSuggestions";
import { Button, Skeleton, Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { leaveSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { useMinuteNow } from "@posthog/ui/hooks/useMinuteNow";
import { SearchInput } from "@posthog/ui/primitives/SearchInput";
import { track } from "@posthog/ui/shell/analytics";
import { Link } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useMeQuery } from "../../auth/useMeQuery";
import { useScoutConfigMutations } from "../hooks/useScoutConfigMutations";
import { useScoutConfigs } from "../hooks/useScoutConfigs";
import { useScoutFleetSync } from "../hooks/useScoutFleetSync";
import {
  useScoutOutputSummary,
  useScoutRecentRuns,
} from "../hooks/useScoutRecentRuns";
import { useScoutSkillCreators } from "../hooks/useScoutSkillCreators";
import {
  useDismissScoutSuggestion,
  useScoutSuggestions,
} from "../hooks/useScoutSuggestions";
import { useTrackFleetViewed } from "../hooks/useTrackFleetViewed";
import { ScoutAttentionStrip } from "./ScoutAttentionStrip";
import { ScoutSuggestions } from "./ScoutSuggestions";
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
export function ScoutsFleetView({
  onNewAgent,
}: {
  onNewAgent: (brief?: string) => void;
}) {
  const now = useMinuteNow();
  const configsQuery = useScoutConfigs();
  const { data: configs, isLoading, isError, refetch } = configsQuery;
  // Opening this page is what materializes the fleet, so a project the
  // coordinator never reached still gets its scouts.
  const { isSyncing, syncOutcome } = useScoutFleetSync();
  const runsQuery = useScoutRecentRuns();
  const outputQuery = useScoutOutputSummary();
  const recentRuns = runsQuery.data;
  // Run history arrives after the fleet, so the columns it feeds say "loading",
  // never "none", until the window has answered.
  const runsPending = runsQuery.isLoading;
  const runsLoadingMore = runsQuery.isFetching;
  const { data: creators } = useScoutSkillCreators();
  const { data: currentUser } = useMeQuery();
  const { updateConfig } = useScoutConfigMutations();
  const { data: suggestions } = useScoutSuggestions();
  const dismissSuggestion = useDismissScoutSuggestion();
  useTrackFleetViewed(
    configs,
    syncOutcome,
    configsQuery.isFetchedAfterMount && !configsQuery.isFetching && !isError,
  );

  const [originChoice, setOriginChoice] = useState<OriginFilter | null>(null);
  const [search, setSearch] = useState("");
  const [creatorKey, setCreatorKey] = useState("");
  const [hideDisabled, setHideDisabled] = useState(false);

  const allConfigs = configs ?? EMPTY_CONFIGS;
  const rollups = useMemo(
    () => computeScoutRollups(recentRuns ?? []),
    [recentRuns],
  );
  const summary = useMemo(
    () => computeFleetSummary(allConfigs, rollups, now),
    [allConfigs, rollups, now],
  );
  const attention = useMemo(
    () => listScoutsNeedingAttention(allConfigs, rollups, now),
    [allConfigs, rollups, now],
  );
  const originCounts = useMemo(() => {
    const counts: Record<OriginFilter, number> = {
      custom: 0,
      canonical: 0,
      all: 0,
    };
    for (const config of allConfigs) {
      counts[getScoutOrigin(config)] += 1;
      counts.all += 1;
    }
    return counts;
  }, [allConfigs]);
  // Custom agents are the ones a person wrote, so they lead when there are any.
  const origin: OriginFilter =
    originChoice ?? (originCounts.custom > 0 ? "custom" : "all");

  const creatorOptions = useMemo(
    () => (creators ? listScoutCreatorOptions(creators, currentUser) : []),
    [creators, currentUser],
  );

  // The order depends on the fleet alone, so a keystroke in the search box
  // filters what is already sorted rather than sorting it again.
  const orderedConfigs = useMemo(() => {
    const urgent = new Set(attention.map((item) => item.config.id));
    return sortConfigsForDisplay(allConfigs).sort(
      (a, b) => Number(urgent.has(b.id)) - Number(urgent.has(a.id)),
    );
  }, [allConfigs, attention]);

  const visibleConfigs = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return orderedConfigs.filter((config) => {
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
  }, [orderedConfigs, origin, hideDisabled, creatorKey, creators, search]);

  if (isLoading || (isSyncing && !configs?.length)) {
    return <FleetSkeleton />;
  }

  if (isError && !configs) {
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

  const suggestionCards = (
    <ScoutSuggestions
      items={suggestions?.items ?? []}
      configs={allConfigs}
      onTurnOn={updateConfig}
      onDraft={(item) => onNewAgent(suggestionBrief(item))}
      onDismiss={dismissSuggestion}
    />
  );

  if (!configs || configs.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        {suggestionCards}
        <ScoutsEmptyState onNewAgent={onNewAgent} />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-5">
      {isError || runsQuery.isError || outputQuery.isError ? (
        <output className="text-(--amber-11) text-[12.5px]">
          Some agent data could not refresh. Available data remains visible.{" "}
          <button
            type="button"
            className="underline"
            onClick={() => {
              void refetch();
              void runsQuery.refetch();
              void outputQuery.refetch();
            }}
          >
            Retry
          </button>
        </output>
      ) : null}
      <p className="flex flex-wrap items-center gap-x-1.5 text-[12.5px] text-gray-10">
        <span>
          <Stat value={summary.enabledCount} /> of {summary.totalCount} enabled
        </span>
        <Dot />
        {runsPending ? (
          <Skeleton className="h-3.5 w-52" />
        ) : (
          <>
            {summary.runningCount > 0 ? (
              <>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-(--blue-9)" />
                  <Stat value={summary.runningCount} /> running now
                </span>
                <Dot />
              </>
            ) : null}
            {summary.successRate !== null ? (
              <>
                <span>
                  <Stat value={`${Math.round(summary.successRate * 100)}%`} />{" "}
                  success in shown runs
                </span>
                <Dot />
              </>
            ) : null}
            <span>
              {outputQuery.data ? (
                <>
                  <Link
                    to="/inbox"
                    onClick={leaveSettings}
                    className="underline"
                  >
                    <Stat
                      value={
                        outputQuery.data.authored_report_count +
                        outputQuery.data.edited_report_count
                      }
                    />{" "}
                    reports
                  </Link>{" "}
                  from recent output runs in the {SCOUT_RUNS_WINDOW_LABEL}
                </>
              ) : outputQuery.isError ? (
                "Output totals are unavailable"
              ) : (
                "Loading output totals"
              )}
            </span>
            {runsLoadingMore ? (
              <span className="animate-pulse text-gray-9">· refreshing</span>
            ) : null}
          </>
        )}
        <span className="flex-1" />
        {/* One span, so a wrap never leaves its separator hanging on a line. */}
        {summary.systemPausedCount > 0 || summary.pausingSoonCount > 0 ? (
          <span className="text-(--amber-11)">
            {[
              summary.systemPausedCount > 0
                ? `${summary.systemPausedCount} auto-paused`
                : null,
              summary.pausingSoonCount > 0
                ? `${summary.pausingSoonCount} pausing soon`
                : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </span>
        ) : null}
      </p>

      {suggestionCards}
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
              <TabsTrigger key={value} value={value} className="px-2.5">
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <SearchInput
          className="w-52"
          value={search}
          onValueChange={setSearch}
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
        />
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
              size="default"
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

      <div className="min-h-0 flex-1">
        <ScoutTable
          configs={visibleConfigs}
          rollups={rollups}
          runsPending={runsPending}
          creators={creators}
          onUpdateConfig={updateConfig}
          emptyMessage={
            search.trim()
              ? "No agents match your search."
              : "No agents match the current filters."
          }
        />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-gray-10">
        <span className="flex items-center gap-3">
          <Legend className="bg-(--iris-9)" label="output" />
          <Legend className="bg-(--gray-6)" label="quiet" />
          <Legend className="bg-(--red-9)" label="failed" />
        </span>
        <span>
          Showing {visibleConfigs.length} of {configs.length} agents. Each row
          shows up to 18 recent runs.
        </span>
        {origin !== "custom" ? (
          <span>
            PostHog owns the built-in agents. You can switch them on or off. You
            cannot edit them.
          </span>
        ) : null}
      </div>
    </div>
  );
}

const SKELETON_ROWS = [0, 1, 2, 3, 4, 5];

/** The shape of the loaded page, so the layout does not jump when it lands. */
function FleetSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <Skeleton className="h-4 w-96" />
      <div className="flex items-center gap-2">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-8 w-52" />
      </div>
      <div className="flex flex-col gap-px overflow-hidden rounded-(--radius-md) border border-border bg-(--color-panel-solid) p-3">
        {SKELETON_ROWS.map((row) => (
          <div key={row} className="flex items-center gap-4 py-2.5">
            <Skeleton className="h-4 w-64" />
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-4 w-32" />
          </div>
        ))}
      </div>
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
