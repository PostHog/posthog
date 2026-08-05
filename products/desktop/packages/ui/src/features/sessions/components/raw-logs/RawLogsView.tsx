import type { AcpMessage } from "@posthog/shared";
import { RawLogEntry } from "@posthog/ui/features/sessions/components/raw-logs/RawLogEntry";
import { RawLogsHeader } from "@posthog/ui/features/sessions/components/raw-logs/RawLogsHeader";
import { VirtualizedList } from "@posthog/ui/features/sessions/components/VirtualizedList";
import {
  useSearchQuery,
  useSessionViewActions,
  useShowSearch,
} from "@posthog/ui/features/sessions/sessionViewStore";
import { Divider } from "@posthog/ui/primitives/Divider";
import { Box, Flex } from "@radix-ui/themes";
import { useCallback, useMemo, useRef } from "react";

interface RawLogsViewProps {
  events: AcpMessage[];
  onClose: () => void;
}

interface FilteredEvent {
  event: AcpMessage;
  originalIndex: number;
}

export function RawLogsView({ events, onClose }: RawLogsViewProps) {
  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchQuery = useSearchQuery();
  const showSearch = useShowSearch();
  const { setSearchQuery, toggleSearch } = useSessionViewActions();

  const filteredEvents = useMemo<FilteredEvent[]>(() => {
    if (!searchQuery.trim()) {
      return events.map((event, index) => ({ event, originalIndex: index }));
    }
    const query = searchQuery.toLowerCase();
    return events
      .map((event, index) => ({ event, originalIndex: index }))
      .filter(({ event }) =>
        JSON.stringify(event).toLowerCase().includes(query),
      );
  }, [events, searchQuery]);

  const copyToClipboard = useCallback((text: string) => {
    navigator.clipboard.writeText(text);
  }, []);

  const copyAllLogs = useCallback(() => {
    const logsToExport = filteredEvents.map(({ event }) => event);
    const allLogs = JSON.stringify(logsToExport, null, 2);
    navigator.clipboard.writeText(allLogs);
  }, [filteredEvents]);

  const renderRawLogEntry = useCallback(
    ({ event, originalIndex }: FilteredEvent, index: number) => (
      <Box>
        <RawLogEntry
          event={event}
          index={originalIndex}
          onCopy={copyToClipboard}
        />
        {index < filteredEvents.length - 1 && <Divider size="1" />}
      </Box>
    ),
    [copyToClipboard, filteredEvents.length],
  );

  return (
    <Flex direction="column" className="flex-1 overflow-hidden">
      <RawLogsHeader
        filteredCount={filteredEvents.length}
        totalCount={events.length}
        searchQuery={searchQuery}
        showSearch={showSearch}
        onToggleSearch={toggleSearch}
        onCopyAll={copyAllLogs}
        onClose={onClose}
        onSearchChange={setSearchQuery}
        searchInputRef={searchInputRef}
      />
      <VirtualizedList
        items={filteredEvents}
        getItemKey={({ originalIndex }) => originalIndex}
        renderItem={renderRawLogEntry}
        className="flex-1 px-4"
      />
    </Flex>
  );
}
