import { Copy, MagnifyingGlass, X } from "@phosphor-icons/react";
import { Box, Flex, IconButton, Text, TextField } from "@radix-ui/themes";
import type { RefObject } from "react";

interface RawLogsHeaderProps {
  filteredCount: number;
  totalCount: number;
  searchQuery: string;
  showSearch: boolean;
  onToggleSearch: () => void;
  onCopyAll: () => void;
  onClose: () => void;
  onSearchChange: (query: string) => void;
  searchInputRef: RefObject<HTMLInputElement | null>;
}

export function RawLogsHeader({
  filteredCount,
  totalCount,
  searchQuery,
  showSearch,
  onToggleSearch,
  onCopyAll,
  onClose,
  onSearchChange,
  searchInputRef,
}: RawLogsHeaderProps) {
  return (
    <Box className="p-4 pb-2">
      <Flex direction="column" gap="2">
        <Flex justify="between" align="center">
          <Text color="gray" className="font-medium text-base">
            Raw Logs ({filteredCount}
            {searchQuery && ` of ${totalCount}`} events)
          </Text>
          <Flex gap="3">
            <IconButton
              size="2"
              variant="ghost"
              color="gray"
              onClick={() => {
                onToggleSearch();
                if (!showSearch) {
                  setTimeout(() => searchInputRef.current?.focus(), 0);
                }
              }}
              title="Search logs"
            >
              <MagnifyingGlass size={16} />
            </IconButton>
            <IconButton
              size="2"
              variant="ghost"
              color="gray"
              onClick={onCopyAll}
              title="Copy all logs"
            >
              <Copy size={16} />
            </IconButton>
            <IconButton
              size="2"
              variant="ghost"
              color="gray"
              onClick={onClose}
              title="Back to conversation"
            >
              <X size={16} />
            </IconButton>
          </Flex>
        </Flex>
        {showSearch && (
          <TextField.Root
            ref={searchInputRef}
            size="1"
            placeholder="Search logs... (Esc to close)"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
          >
            <TextField.Slot>
              <MagnifyingGlass size={12} />
            </TextField.Slot>
          </TextField.Root>
        )}
      </Flex>
    </Box>
  );
}
