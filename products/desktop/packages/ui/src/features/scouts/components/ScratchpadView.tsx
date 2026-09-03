import {
  CaretDownIcon,
  ClockIcon,
  MagnifyingGlassIcon,
  StackIcon,
} from "@phosphor-icons/react";
import {
  filterScratchpadEntries,
  groupScratchpadEntries,
  type ScratchpadGrouping,
} from "@posthog/core/scouts/scoutScratchpad";
import { Input, Tabs, TabsList, TabsTrigger } from "@posthog/quill";
import { AgentsTabLayout } from "@posthog/ui/features/agents/components/AgentsTabLayout";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Box, Flex, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import { useScoutScratchpad } from "../hooks/useScoutScratchpad";
import { ScratchpadEntryCard } from "./ScratchpadEntryCard";

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
  const allEntries = entries ?? [];
  const visibleEntries = useMemo(
    () => filterScratchpadEntries(allEntries, searchText),
    [allEntries, searchText],
  );
  const groups = useMemo(
    () => groupScratchpadEntries(visibleEntries),
    [visibleEntries],
  );

  const totalCount = entries?.length ?? null;
  const lastUpdatedAt = entries?.[0]?.updated_at ?? null;

  return (
    <AgentsTabLayout tab="memory" counts={{ memory: totalCount ?? undefined }}>
      <Flex direction="column" gap="4">
        {totalCount !== null && totalCount > 0 ? (
          <Flex align="center" gap="1" className="text-[12px] text-gray-10">
            <Text className="text-[12px] text-gray-10">
              {totalCount >= 500
                ? "Latest 500 notes"
                : `${totalCount} note${totalCount === 1 ? "" : "s"}`}
            </Text>
            {lastUpdatedAt ? (
              <>
                <Text className="text-[12px] text-gray-9">· last updated</Text>
                <RelativeTimestamp
                  timestamp={lastUpdatedAt}
                  className="text-[12px] text-gray-10"
                />
              </>
            ) : null}
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
              placeholder="Search notes"
              aria-label="Search notes"
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              className="h-8 pl-7"
            />
          </div>
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

        <ScratchpadBody
          isLoading={isLoading}
          isError={isError}
          onRetry={() => refetch()}
          entries={visibleEntries}
          groups={groups}
          grouping={grouping}
          isSearching={isSearching}
        />
      </Flex>
    </AgentsTabLayout>
  );
}

function ScratchpadBody({
  isLoading,
  isError,
  onRetry,
  entries,
  groups,
  grouping,
  isSearching,
}: {
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  entries: ReturnType<typeof filterScratchpadEntries>;
  groups: ReturnType<typeof groupScratchpadEntries>;
  grouping: ScratchpadGrouping;
  isSearching: boolean;
}) {
  if (isLoading) {
    return (
      <Flex direction="column" gap="2">
        {[0, 1, 2].map((key) => (
          <Box
            key={key}
            className="h-12 w-full animate-pulse rounded-(--radius-2) bg-(--gray-3)"
          />
        ))}
      </Flex>
    );
  }

  if (isError) {
    return (
      <Flex
        direction="column"
        align="center"
        gap="2"
        className="rounded-(--radius-2) border border-(--gray-6) border-dashed bg-gray-1 px-4 py-8 text-center text-[12.5px] text-gray-11"
      >
        <Text className="text-[12.5px] text-gray-11">
          Couldn&apos;t load the scratchpad. The scout API may be unavailable or
          this project may not be enrolled yet.
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

  if (entries.length === 0) {
    return (
      <Box className="rounded-(--radius-2) border border-(--gray-6) border-dashed bg-gray-1 px-4 py-8 text-center text-[12.5px] text-gray-11">
        {isSearching
          ? "No notes match your search."
          : "Your agents haven't written anything down yet. As they scan your project, their notes show up here."}
      </Box>
    );
  }

  if (grouping === "topic") {
    return (
      <Flex direction="column" gap="3">
        {groups.map((group) => (
          <ScratchpadTopicGroup
            key={group.namespace}
            label={group.label}
            entries={group.entries}
            // A search forces every matching topic open so results stay visible
            // without a click.
            forceOpen={isSearching}
          />
        ))}
      </Flex>
    );
  }

  return (
    <Flex direction="column" gap="2">
      {entries.map((entry) => (
        <ScratchpadEntryCard key={entry.key} entry={entry} />
      ))}
    </Flex>
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
    <Flex direction="column" gap="2">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={isExpanded}
        className="flex items-center gap-2 text-left"
      >
        <CaretDownIcon
          size={14}
          className={`shrink-0 text-gray-9 transition-transform ${isExpanded ? "" : "-rotate-90"}`}
        />
        <Text className="font-medium text-[12px] text-gray-11 uppercase tracking-wide">
          {label}
        </Text>
        <Text className="text-[11px] text-gray-10">
          {entries.length} note{entries.length === 1 ? "" : "s"}
        </Text>
      </button>
      {isExpanded
        ? entries.map((entry) => (
            <ScratchpadEntryCard key={entry.key} entry={entry} />
          ))
        : null}
    </Flex>
  );
}
