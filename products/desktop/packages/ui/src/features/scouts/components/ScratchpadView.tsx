import { CaretDownIcon, ClockIcon, StackIcon } from "@phosphor-icons/react";
import type { ScoutScratchpadEntry } from "@posthog/api-client/posthog-client";
import {
  filterScratchpadEntries,
  groupScratchpadEntries,
  type ScratchpadGrouping,
} from "@posthog/core/scouts/scoutScratchpad";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Skeleton,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { SearchInput } from "@posthog/ui/primitives/SearchInput";
import { useMemo, useState } from "react";
import { useScoutScratchpad } from "../hooks/useScoutScratchpad";
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
  const [expandedNotes, setExpandedNotes] = useState<Record<string, boolean>>(
    {},
  );
  const [expandedTopics, setExpandedTopics] = useState<Record<string, boolean>>(
    {},
  );
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

      {isLoading ? (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-14 w-full" />
          ))}
        </div>
      ) : isError && entries === undefined ? (
        <Empty className="py-10">
          <EmptyHeader>
            <EmptyDescription>
              Couldn't load these notes. PostHog may be unavailable, or this
              project may not be set up for agents yet.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => refetch()}
            >
              Retry
            </Button>
          </EmptyContent>
        </Empty>
      ) : visibleEntries.length === 0 ? (
        <Empty className="py-10">
          <EmptyHeader>
            <EmptyTitle>
              {isSearching
                ? "No notes match your search."
                : "Your agents haven't written anything down yet. As they scan your project, their notes show up here."}
            </EmptyTitle>
          </EmptyHeader>
        </Empty>
      ) : (
        <VirtualCardList
          resetKey={`${grouping}:${searchText}`}
          items={
            grouping === "topic"
              ? groups.flatMap((group): MemoryRow[] => [
                  { kind: "topic", group },
                  ...(isSearching || expandedTopics[group.namespace]
                    ? group.entries.map(
                        (entry): MemoryRow => ({ kind: "note", entry }),
                      )
                    : []),
                ])
              : visibleEntries.map(
                  (entry): MemoryRow => ({ kind: "note", entry }),
                )
          }
          getKey={(row) =>
            row.kind === "topic"
              ? `topic:${row.group.namespace}`
              : `note:${row.entry.key}`
          }
          estimateSize={NOTE_CARD_HEIGHT}
          renderItem={(row) =>
            row.kind === "topic" ? (
              <button
                type="button"
                onClick={() =>
                  setExpandedTopics((state) => ({
                    ...state,
                    [row.group.namespace]: !state[row.group.namespace],
                  }))
                }
                aria-expanded={
                  isSearching || !!expandedTopics[row.group.namespace]
                }
                className="flex w-full items-center gap-2 py-2 text-left text-[12px] text-gray-11"
              >
                <CaretDownIcon
                  size={14}
                  className={
                    isSearching || expandedTopics[row.group.namespace]
                      ? ""
                      : "-rotate-90"
                  }
                />
                {row.group.label} · {row.group.entries.length} notes
              </button>
            ) : (
              <ScratchpadEntryCard
                entry={row.entry}
                expanded={expandedNotes[row.entry.key] ?? false}
                onExpandedChange={(value) =>
                  setExpandedNotes((state) => ({
                    ...state,
                    [row.entry.key]: value,
                  }))
                }
              />
            )
          }
        />
      )}
    </div>
  );
}

type MemoryRow =
  | { kind: "topic"; group: ReturnType<typeof groupScratchpadEntries>[number] }
  | { kind: "note"; entry: ScoutScratchpadEntry };
