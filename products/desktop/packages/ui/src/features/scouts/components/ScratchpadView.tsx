import { CaretDownIcon, ClockIcon, StackIcon } from "@phosphor-icons/react";
import type { ScoutScratchpadEntry } from "@posthog/api-client/posthog-client";
import {
  filterScratchpadEntries,
  groupScratchpadEntries,
  type ScratchpadGrouping,
} from "@posthog/core/scouts/scoutScratchpad";
import { Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { SearchInput } from "@posthog/ui/primitives/SearchInput";
import { useMemo, useState } from "react";
import { useScoutScratchpad } from "../hooks/useScoutScratchpad";
import { ScoutListBody } from "./ScoutListBody";
import { ScratchpadEntryCard } from "./ScratchpadEntryCard";
import { VirtualCardList } from "./VirtualCardList";

/** A collapsed note: header line plus a two-line preview. */
const NOTE_CARD_HEIGHT = 84;

const EMPTY_ENTRIES: ScoutScratchpadEntry[] = [];
const NO_GROUPS: ReturnType<typeof groupScratchpadEntries> = [];

/**
 * Browse + search surface for the scout fleet's scratchpad (`SignalScratchpad`).
 * Frames what the scratchpad is up top, then lets the user read it newest-first
 * or clustered by topic, and search it. Read-only: the harness writes the notes
 * on internal scope; humans inspect them here.
 *
 * Mirrors the PostHog Cloud `ScratchpadPanel`, kept structurally aligned so the
 * two surfaces stay in parity as the backend evolves.
 */
export function ScratchpadView() {
  const { data: entries, isLoading, isError, refetch } = useScoutScratchpad();
  const [searchText, setSearchText] = useState("");
  const [grouping, setGrouping] = useState<ScratchpadGrouping>("recent");

  const isSearching = searchText.trim().length > 0;
  const allEntries = entries ?? EMPTY_ENTRIES;
  const visibleEntries = useMemo(
    () => filterScratchpadEntries(allEntries, searchText),
    [allEntries, searchText],
  );
  // Only the topic view reads the groups, and "recent" is where people land.
  const groups = useMemo(
    () =>
      grouping === "topic" ? groupScratchpadEntries(visibleEntries) : NO_GROUPS,
    [visibleEntries, grouping],
  );

  const totalCount = entries?.length ?? null;
  const lastUpdatedAt = entries?.[0]?.updated_at ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      {totalCount !== null && totalCount > 0 ? (
        <div className="flex items-center gap-1 text-[12px] text-gray-10">
          <span>
            {totalCount >= 500
              ? "Latest 500 notes"
              : `${totalCount} note${totalCount === 1 ? "" : "s"}`}
          </span>
          {lastUpdatedAt ? (
            <>
              <span className="text-gray-9">· last updated</span>
              <RelativeTimestamp
                timestamp={lastUpdatedAt}
                className="text-[12px] text-gray-10"
              />
            </>
          ) : null}
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={searchText}
          onValueChange={setSearchText}
          placeholder="Search notes"
        />
        <span className="flex-1" />
        <Tabs
          value={grouping}
          onValueChange={(value: string) =>
            setGrouping(value as ScratchpadGrouping)
          }
        >
          <TabsList className="h-8" aria-label="Group notes">
            <TabsTrigger value="recent" className="gap-1.5 px-2.5">
              <ClockIcon size={12} />
              Recent
            </TabsTrigger>
            <TabsTrigger value="topic" className="gap-1.5 px-2.5">
              <StackIcon size={12} />
              By topic
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <ScoutListBody
        loading={isLoading}
        failed={isError}
        empty={visibleEntries.length === 0}
        errorMessage="Couldn't load these notes. PostHog may be unavailable, or this project may not be set up for agents yet."
        emptyMessage={
          isSearching
            ? "No notes match your search."
            : "Your agents haven't written anything down yet. As they scan your project, their notes show up here."
        }
        onRetry={() => refetch()}
      >
        {grouping === "topic" ? (
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
            {groups.map((group) => (
              <ScratchpadTopicGroup
                key={group.namespace}
                label={group.label}
                entries={group.entries}
                // A search forces every matching topic open so results stay
                // visible without a click.
                forceOpen={isSearching}
              />
            ))}
          </div>
        ) : (
          <VirtualCardList
            items={visibleEntries}
            getKey={(entry) => entry.key}
            estimateSize={NOTE_CARD_HEIGHT}
            renderItem={(entry) => <ScratchpadEntryCard entry={entry} />}
          />
        )}
      </ScoutListBody>
    </div>
  );
}

function ScratchpadTopicGroup({
  label,
  entries,
  forceOpen,
}: {
  label: string;
  entries: ReturnType<typeof filterScratchpadEntries>;
  forceOpen: boolean;
}) {
  // Collapsed by default for a high-level scan; a search forces it open.
  const [expanded, setExpanded] = useState(false);
  const isExpanded = forceOpen || expanded;

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={isExpanded}
        className="flex cursor-pointer items-center gap-2 border-0 bg-transparent p-0 text-left"
      >
        <CaretDownIcon
          size={14}
          className={`shrink-0 text-gray-9 transition-transform ${isExpanded ? "" : "-rotate-90"}`}
        />
        <span className="font-medium text-[12px] text-gray-11 uppercase tracking-wide">
          {label}
        </span>
        <span className="text-[11px] text-gray-10">
          {entries.length} note{entries.length === 1 ? "" : "s"}
        </span>
      </button>
      {isExpanded
        ? entries.map((entry) => (
            <ScratchpadEntryCard key={entry.key} entry={entry} />
          ))
        : null}
    </div>
  );
}
