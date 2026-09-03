import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import {
  availableScoutsFromRows,
  filterAndSortScoutFindings,
  SCOUT_FINDINGS_SCOUT_FILTER_ALL,
  SCOUT_FINDINGS_SEVERITY_FILTER_ALL,
  SCOUT_FINDINGS_SEVERITY_OPTIONS,
  type ScoutFindingsSortKey,
  summarizeScoutFindingRows,
} from "@posthog/core/scouts/scoutFindings";
import { prettifyScoutSkillName } from "@posthog/core/scouts/scoutPresentation";
import { SCOUT_RUNS_WINDOW_SPAN } from "@posthog/core/scouts/scoutRunsWindow";
import { Input } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { AgentsTabLayout } from "@posthog/ui/features/agents/components/AgentsTabLayout";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { track } from "@posthog/ui/shell/analytics";
import { Box, Flex, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import { useScoutFindings } from "../hooks/useScoutFindings";
import { ScoutEmissionCard } from "./ScoutEmissionCard";

const SORT_OPTIONS: { value: ScoutFindingsSortKey; label: string }[] = [
  { value: "newest", label: "Newest" },
  { value: "oldest", label: "Oldest" },
  { value: "severity", label: "Severity" },
  { value: "confidence", label: "Confidence" },
];

/**
 * Cross-fleet findings browser — every finding the troop emitted recently in one
 * place, newest first, searchable and filterable by scout/severity with a sort
 * toggle. Reuses the per-scout {@link ScoutEmissionCard} with the emitting
 * scout's name shown. Read-only: acting on a finding happens in its inbox report.
 *
 * Mirrors the PostHog Cloud `FindingsPanel`, kept structurally aligned so the two
 * surfaces stay in parity as the backend evolves.
 */
export function ScoutFindingsView() {
  const {
    rows,
    hasLoadedOnce,
    runsError,
    emissionsError,
    emissionsFetching,
    refetch,
  } = useScoutFindings();

  const [searchText, setSearchText] = useState("");
  const [scoutFilter, setScoutFilter] = useState<string>(
    SCOUT_FINDINGS_SCOUT_FILTER_ALL,
  );
  const [severityFilter, setSeverityFilter] = useState<string>(
    SCOUT_FINDINGS_SEVERITY_FILTER_ALL,
  );
  const [sortKey, setSortKey] = useState<ScoutFindingsSortKey>("newest");

  const availableScouts = useMemo(() => availableScoutsFromRows(rows), [rows]);
  const summary = useMemo(() => summarizeScoutFindingRows(rows), [rows]);
  const filteredRows = useMemo(
    () =>
      filterAndSortScoutFindings(rows, {
        search: searchText,
        scout: scoutFilter,
        severity: severityFilter,
        sort: sortKey,
      }),
    [rows, searchText, scoutFilter, severityFilter, sortKey],
  );

  const isFiltering =
    searchText.trim().length > 0 ||
    scoutFilter !== SCOUT_FINDINGS_SCOUT_FILTER_ALL ||
    severityFilter !== SCOUT_FINDINGS_SEVERITY_FILTER_ALL;

  // A failed initial load with nothing on screen, vs a stale list whose later
  // refresh failed — the former is a full error state, the latter a warning that
  // the list may be incomplete.
  const loadFailed = emissionsError || runsError;

  return (
    <AgentsTabLayout tab="signals" counts={{ signals: summary.totalCount }}>
      <Flex direction="column" gap="4">
        {summary.totalCount > 0 ? (
          <Flex
            align="center"
            gap="1"
            className="text-[12px] text-gray-10"
            wrap="wrap"
          >
            <Text className="text-[12px] text-gray-10">
              {summary.totalCount} signal
              {summary.totalCount === 1 ? "" : "s"} · {summary.scoutCount} agent
              {summary.scoutCount === 1 ? "" : "s"}
            </Text>
            {summary.latestEmittedAt ? (
              <>
                <Text className="text-[12px] text-gray-9">· latest</Text>
                <RelativeTimestamp
                  timestamp={summary.latestEmittedAt}
                  className="text-[12px] text-gray-10"
                />
              </>
            ) : null}
            <Text className="text-[12px] text-gray-9">
              · from the most recent {SCOUT_RUNS_WINDOW_SPAN} of runs
            </Text>
          </Flex>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-64">
            <MagnifyingGlassIcon
              size={13}
              className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-2.5 text-gray-10"
            />
            <Input
              type="search"
              placeholder="Search signals"
              aria-label="Search signals"
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              className="h-8 pl-7"
            />
          </div>
          <div className="w-44">
            <SettingsOptionSelect
              value={scoutFilter}
              options={[
                { value: SCOUT_FINDINGS_SCOUT_FILTER_ALL, label: "All agents" },
                ...availableScouts.map((scout) => ({
                  value: scout.skillName,
                  label: `${scout.label} (${scout.count})`,
                })),
              ]}
              ariaLabel="Filter by agent"
              onValueChange={(value) => {
                setScoutFilter(value);
                track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                  action_type: "filter_findings",
                  surface: "scout_findings",
                  filter: value,
                });
              }}
            />
          </div>
          <div className="w-36">
            <SettingsOptionSelect
              value={severityFilter}
              options={[
                {
                  value: SCOUT_FINDINGS_SEVERITY_FILTER_ALL,
                  label: "All severities",
                },
                ...SCOUT_FINDINGS_SEVERITY_OPTIONS.map((severity) => ({
                  value: severity,
                  label: severity,
                })),
              ]}
              ariaLabel="Filter by severity"
              onValueChange={(value) => {
                setSeverityFilter(value);
                track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                  action_type: "filter_findings",
                  surface: "scout_findings",
                  filter: `severity:${value}`,
                });
              }}
            />
          </div>
          <span className="flex-1" />
          <div className="w-40">
            <SettingsOptionSelect
              value={sortKey}
              options={SORT_OPTIONS.map((option) => ({
                value: option.value,
                label: `Sort: ${option.label}`,
              }))}
              ariaLabel="Sort signals"
              onValueChange={(value) => {
                const next = value as ScoutFindingsSortKey;
                setSortKey(next);
                track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                  action_type: "sort_findings",
                  surface: "scout_findings",
                  filter: next,
                });
              }}
            />
          </div>
        </div>

        {hasLoadedOnce &&
        (emissionsError || runsError) &&
        emissionsFetching === false &&
        rows.length > 0 ? (
          // A later poll/retry failed while a prior set is still on screen.
          // The list may be incomplete — warn rather than show it silently.
          <Flex
            align="center"
            gap="3"
            className="rounded-(--radius-2) border border-(--amber-6) bg-(--amber-2) px-4 py-3 text-[12.5px]"
          >
            <Text className="flex-1 text-(--amber-11)">
              Some signals couldn&apos;t be loaded, so this list may be
              incomplete.
            </Text>
            <button
              type="button"
              onClick={() => refetch()}
              className="shrink-0 rounded-(--radius-2) border border-(--amber-7) px-2.5 py-1 text-(--amber-11) transition-colors hover:bg-(--amber-3)"
            >
              Retry
            </button>
          </Flex>
        ) : null}

        <FindingsBody
          hasLoadedOnce={hasLoadedOnce}
          loadFailed={loadFailed}
          rowCount={rows.length}
          filteredRows={filteredRows}
          isFiltering={isFiltering}
          onRetry={refetch}
        />
      </Flex>
    </AgentsTabLayout>
  );
}

function FindingsBody({
  hasLoadedOnce,
  loadFailed,
  rowCount,
  filteredRows,
  isFiltering,
  onRetry,
}: {
  hasLoadedOnce: boolean;
  loadFailed: boolean;
  rowCount: number;
  filteredRows: ReturnType<typeof filterAndSortScoutFindings>;
  isFiltering: boolean;
  onRetry: () => void;
}) {
  if (!hasLoadedOnce) {
    return (
      <Flex direction="column" gap="2">
        {[0, 1, 2].map((key) => (
          <Box
            key={key}
            className="h-14 w-full animate-pulse rounded-(--radius-2) bg-(--gray-3)"
          />
        ))}
      </Flex>
    );
  }

  if (loadFailed && rowCount === 0) {
    return (
      <Flex
        direction="column"
        align="center"
        gap="2"
        className="rounded-(--radius-2) border border-(--gray-6) border-dashed bg-gray-1 px-4 py-8 text-center text-[12.5px] text-gray-11"
      >
        <Text className="text-[12.5px] text-gray-11">
          Couldn&apos;t load signals. The scout API may be unavailable or this
          project may not be enrolled yet.
        </Text>
        <button
          type="button"
          onClick={onRetry}
          className="rounded-(--radius-2) border border-(--gray-7) px-2.5 py-1 text-[12px] text-gray-11 transition-colors hover:bg-(--gray-3)"
        >
          Retry
        </button>
      </Flex>
    );
  }

  if (filteredRows.length === 0) {
    return (
      <Box className="rounded-(--radius-2) border border-(--gray-6) border-dashed bg-gray-1 px-4 py-8 text-center text-[12.5px] text-gray-11">
        {isFiltering
          ? "No signals match your search and filters."
          : "Your agents haven't sent any signals yet. As they scan your project, what they surface shows up here."}
      </Box>
    );
  }

  return (
    <Flex direction="column" gap="2">
      {filteredRows.map((row) => (
        <ScoutEmissionCard
          // emission.id, not source_id — a run can re-emit a finding_id, sharing source_id.
          key={row.emission.id}
          emission={row.emission}
          skillName={row.run.skill_name}
          scoutLabel={prettifyScoutSkillName(row.run.skill_name)}
          linkedReport={row.linkedReport}
        />
      ))}
    </Flex>
  );
}
