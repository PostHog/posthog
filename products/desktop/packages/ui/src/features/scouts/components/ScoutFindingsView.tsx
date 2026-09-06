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
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { SearchInput } from "@posthog/ui/primitives/SearchInput";
import { track } from "@posthog/ui/shell/analytics";
import { useMemo, useState } from "react";
import { useScoutFindings } from "../hooks/useScoutFindings";
import { ScoutEmissionCard } from "./ScoutEmissionCard";
import { ScoutListBody } from "./ScoutListBody";
import { VirtualCardList } from "./VirtualCardList";

/** A collapsed signal card: header, one summary line, footer. */
const SIGNAL_CARD_HEIGHT = 96;

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
    <div className="flex h-full min-h-0 flex-col gap-4">
      {summary.totalCount > 0 ? (
        <div className="flex flex-wrap items-center gap-1 text-[12px] text-gray-10">
          <span>
            {summary.totalCount} signal
            {summary.totalCount === 1 ? "" : "s"} · {summary.scoutCount} agent
            {summary.scoutCount === 1 ? "" : "s"}
          </span>
          {summary.latestEmittedAt ? (
            <>
              <span className="text-gray-9">· latest</span>
              <RelativeTimestamp
                timestamp={summary.latestEmittedAt}
                className="text-[12px] text-gray-10"
              />
            </>
          ) : null}
          <span className="text-gray-9">
            · from the most recent {SCOUT_RUNS_WINDOW_SPAN} of runs
          </span>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={searchText}
          onValueChange={setSearchText}
          placeholder="Search signals"
        />
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
        <div className="flex items-center gap-3 rounded-(--radius-2) border border-(--amber-6) bg-(--amber-2) px-4 py-3 text-[12.5px]">
          <p className="flex-1 text-(--amber-11)">
            Some signals couldn&apos;t be loaded, so this list may be
            incomplete.
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
      ) : null}

      <ScoutListBody
        loading={!hasLoadedOnce}
        failed={loadFailed && rows.length === 0}
        empty={filteredRows.length === 0}
        errorMessage="Couldn't load signals. The scout API may be unavailable or this project may not be enrolled yet."
        emptyMessage={
          isFiltering
            ? "No signals match your search and filters."
            : "Your agents haven't sent any signals yet. As they scan your project, what they surface shows up here."
        }
        onRetry={refetch}
      >
        <VirtualCardList
          items={filteredRows}
          // emission.id, not source_id — a run can re-emit a finding_id, sharing source_id.
          getKey={(row) => row.emission.id}
          estimateSize={SIGNAL_CARD_HEIGHT}
          renderItem={(row) => (
            <ScoutEmissionCard
              emission={row.emission}
              skillName={row.run.skill_name}
              scoutLabel={prettifyScoutSkillName(row.run.skill_name)}
              linkedReport={row.linkedReport}
            />
          )}
        />
      </ScoutListBody>
    </div>
  );
}
