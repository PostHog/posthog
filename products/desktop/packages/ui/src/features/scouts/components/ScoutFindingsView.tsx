import {
  ArrowLeftIcon,
  MagnifyingGlassIcon,
  SparkleIcon,
} from "@phosphor-icons/react";
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
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { track } from "@posthog/ui/shell/analytics";
import { Box, Flex, Select, Text, TextField } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
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

  const headerContent = useMemo(
    () => (
      <Flex align="center" gap="2" className="w-full min-w-0">
        <SparkleIcon size={12} className="shrink-0 text-gray-10" />
        <Text
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title="Scout findings"
        >
          Scout findings
        </Text>
      </Flex>
    ),
    [],
  );
  useSetHeaderContent(headerContent);

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
    <Flex direction="column" className="h-full min-h-0">
      <Flex
        direction="column"
        gap="2"
        className="border-(--gray-5) border-b px-6 pt-5 pb-5"
      >
        <Link
          to="/code/agents/scouts"
          className="flex w-fit items-center gap-1 text-[12px] text-gray-10 no-underline hover:text-gray-12"
        >
          <ArrowLeftIcon size={12} />
          Scouts
        </Link>
        <Flex align="center" gap="2">
          <SparkleIcon size={20} className="shrink-0 text-(--iris-9)" />
          <Text className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
            Scout findings
          </Text>
        </Flex>
        <Text className="max-w-2xl text-pretty text-[12.5px] text-gray-11 leading-relaxed">
          Every signal your scouts have emitted recently, in one place — newest
          first. See what&apos;s been surfaced across the whole troop, which
          scout found it, and the inbox report it fed into.
        </Text>
        <Flex
          align="center"
          gap="1"
          className="text-[12px] text-gray-10"
          wrap="wrap"
        >
          {summary.totalCount > 0 ? (
            <>
              <Text className="text-[12px] text-gray-10">
                {summary.totalCount} finding
                {summary.totalCount === 1 ? "" : "s"} · {summary.scoutCount}{" "}
                scout{summary.scoutCount === 1 ? "" : "s"}
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
            </>
          ) : null}
        </Flex>
        <Text className="text-[12px] text-gray-9">
          Covers findings from the most recent {SCOUT_RUNS_WINDOW_SPAN} of troop
          runs. Older findings live on in the inbox reports they produced.
        </Text>
      </Flex>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-4xl px-6 py-6">
          <Flex direction="column" gap="4">
            <Flex align="center" gap="2" wrap="wrap">
              <TextField.Root
                type="search"
                placeholder="Search findings…"
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                size="2"
                className="min-w-[12rem] flex-1"
              >
                <TextField.Slot>
                  <MagnifyingGlassIcon size={14} className="text-gray-10" />
                </TextField.Slot>
              </TextField.Root>

              <Select.Root
                value={scoutFilter}
                size="2"
                onValueChange={(value) => {
                  setScoutFilter(value);
                  track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                    action_type: "filter_findings",
                    surface: "scout_findings",
                    filter: value,
                  });
                }}
              >
                <Select.Trigger
                  aria-label="Filter by scout"
                  className="min-w-[9rem]"
                />
                <Select.Content>
                  <Select.Item value={SCOUT_FINDINGS_SCOUT_FILTER_ALL}>
                    All scouts
                  </Select.Item>
                  {availableScouts.map((scout) => (
                    <Select.Item key={scout.skillName} value={scout.skillName}>
                      {scout.label} ({scout.count})
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>

              <Select.Root
                value={severityFilter}
                size="2"
                onValueChange={(value) => {
                  setSeverityFilter(value);
                  track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                    action_type: "filter_findings",
                    surface: "scout_findings",
                    filter: `severity:${value}`,
                  });
                }}
              >
                <Select.Trigger aria-label="Filter by severity" />
                <Select.Content>
                  <Select.Item value={SCOUT_FINDINGS_SEVERITY_FILTER_ALL}>
                    All severities
                  </Select.Item>
                  {SCOUT_FINDINGS_SEVERITY_OPTIONS.map((severity) => (
                    <Select.Item key={severity} value={severity}>
                      {severity}
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>

              <Select.Root
                value={sortKey}
                size="2"
                onValueChange={(value) => {
                  const next = value as ScoutFindingsSortKey;
                  setSortKey(next);
                  track(ANALYTICS_EVENTS.SCOUT_ACTION, {
                    action_type: "sort_findings",
                    surface: "scout_findings",
                    filter: next,
                  });
                }}
              >
                <Select.Trigger aria-label="Sort findings" />
                <Select.Content>
                  {SORT_OPTIONS.map((option) => (
                    <Select.Item key={option.value} value={option.value}>
                      Sort: {option.label}
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
            </Flex>

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
                  Some findings couldn&apos;t be loaded, so this list may be
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
        </div>
      </div>
    </Flex>
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
          Couldn&apos;t load findings. The scout API may be unavailable or this
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
          ? "No findings match your search and filters."
          : "Your scouts haven't emitted any findings yet. As they scan your project, what they surface shows up here."}
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
