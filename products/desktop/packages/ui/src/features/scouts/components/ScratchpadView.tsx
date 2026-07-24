import {
  ArrowLeftIcon,
  CaretDownIcon,
  ClockIcon,
  MagnifyingGlassIcon,
  NotebookIcon,
  StackIcon,
} from "@phosphor-icons/react";
import {
  filterScratchpadEntries,
  groupScratchpadEntries,
  type ScratchpadGrouping,
} from "@posthog/core/scouts/scoutScratchpad";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Box, Flex, SegmentedControl, Text, TextField } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
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

  const headerContent = useMemo(
    () => (
      <Flex align="center" gap="2" className="w-full min-w-0">
        <NotebookIcon size={12} className="shrink-0 text-gray-10" />
        <Text
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title="Scout scratchpad"
        >
          Scout scratchpad
        </Text>
      </Flex>
    ),
    [],
  );
  useSetHeaderContent(headerContent);

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
          <NotebookIcon size={20} className="shrink-0 text-(--iris-9)" />
          <Text className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
            Scout scratchpad
          </Text>
        </Flex>
        <Text className="max-w-2xl text-pretty text-[12.5px] text-gray-11 leading-relaxed">
          Where your scouts jot down useful context as they scan your project —
          things they&apos;ve classified, ruled out, or the vocabulary
          they&apos;ve settled on. Browse it to see what they&apos;re picking up
          about your setup.
        </Text>
        {totalCount !== null && totalCount > 0 ? (
          <Flex align="center" gap="1" className="text-[12px] text-gray-10">
            <Text className="text-[12px] text-gray-10">
              {totalCount} note{totalCount === 1 ? "" : "s"}
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
      </Flex>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-4xl px-6 py-6">
          <Flex direction="column" gap="4">
            <Flex align="center" gap="2" wrap="wrap">
              <TextField.Root
                type="search"
                placeholder="Search the scratchpad…"
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                size="2"
                className="min-w-[14rem] flex-1"
              >
                <TextField.Slot>
                  <MagnifyingGlassIcon size={14} className="text-gray-10" />
                </TextField.Slot>
              </TextField.Root>
              <SegmentedControl.Root
                value={grouping}
                size="1"
                onValueChange={(value) =>
                  setGrouping(value as ScratchpadGrouping)
                }
                aria-label="Scratchpad grouping"
              >
                <SegmentedControl.Item value="recent">
                  <span className="inline-flex items-center gap-1.5">
                    <ClockIcon size={12} />
                    Recent
                  </span>
                </SegmentedControl.Item>
                <SegmentedControl.Item value="topic">
                  <span className="inline-flex items-center gap-1.5">
                    <StackIcon size={12} />
                    By topic
                  </span>
                </SegmentedControl.Item>
              </SegmentedControl.Root>
            </Flex>

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
        </div>
      </div>
    </Flex>
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
          : "Your scouts haven't jotted anything down yet. As they scan your project, their notes show up here."}
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
