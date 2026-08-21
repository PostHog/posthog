import { ChatText, Check, FunnelSimple, X } from "@phosphor-icons/react";
import {
  Autocomplete,
  AutocompleteInput,
  AutocompleteItem,
  AutocompleteList,
  Dialog,
  DialogContent,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { CommandKeyHints } from "@posthog/ui/features/command/CommandKeyHints";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { Flex } from "@radix-ui/themes";
import { useCallback, useMemo, useState } from "react";

interface MessageJumpPickerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  items: ConversationItem[];
  /** Scrolls the thread to the message with this id (ChatThread addresses rows by id, not index). */
  onJumpToMessage: (id: string) => void;
}

interface JumpEntry {
  id: string;
  label: string;
  fullText: string;
  timestamp: number;
}

type DatePreset =
  | "today"
  | "yesterday"
  | "last7d"
  | "last14d"
  | "thisMonth"
  | "lastMonth"
  | "last30d"
  | "last90d"
  | "last6mo"
  | "thisYear"
  | "lastYear";

interface PresetConfig {
  label: string;
  footerLabel: string;
  getRange: () => { from: number; to: number };
}

const DATE_PRESETS: Record<DatePreset, PresetConfig> = {
  today: {
    label: "Today",
    footerLabel: "today",
    getRange: () => {
      const start = new Date();
      start.setHours(0, 0, 0, 0);
      return { from: start.getTime(), to: Date.now() };
    },
  },
  yesterday: {
    label: "Yesterday",
    footerLabel: "yesterday",
    getRange: () => {
      const d = new Date();
      d.setDate(d.getDate() - 1);
      const start = new Date(d);
      start.setHours(0, 0, 0, 0);
      const end = new Date(d);
      end.setHours(23, 59, 59, 999);
      return { from: start.getTime(), to: end.getTime() };
    },
  },
  last7d: {
    label: "Last 7 days",
    footerLabel: "last 7 days",
    getRange: () => {
      const start = new Date();
      start.setDate(start.getDate() - 7);
      start.setHours(0, 0, 0, 0);
      return { from: start.getTime(), to: Date.now() };
    },
  },
  last14d: {
    label: "Last 14 days",
    footerLabel: "last 14 days",
    getRange: () => {
      const start = new Date();
      start.setDate(start.getDate() - 14);
      start.setHours(0, 0, 0, 0);
      return { from: start.getTime(), to: Date.now() };
    },
  },
  thisMonth: {
    label: "This month",
    footerLabel: "this month",
    getRange: () => {
      const start = new Date();
      start.setDate(1);
      start.setHours(0, 0, 0, 0);
      return { from: start.getTime(), to: Date.now() };
    },
  },
  lastMonth: {
    label: "Last month",
    footerLabel: "last month",
    getRange: () => {
      const now = new Date();
      const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      const end = new Date(
        now.getFullYear(),
        now.getMonth(),
        0,
        23,
        59,
        59,
        999,
      );
      return { from: start.getTime(), to: end.getTime() };
    },
  },
  last30d: {
    label: "Last 30 days",
    footerLabel: "last 30 days",
    getRange: () => {
      const start = new Date();
      start.setDate(start.getDate() - 30);
      start.setHours(0, 0, 0, 0);
      return { from: start.getTime(), to: Date.now() };
    },
  },
  last90d: {
    label: "Last 90 days",
    footerLabel: "last 90 days",
    getRange: () => {
      const start = new Date();
      start.setDate(start.getDate() - 90);
      start.setHours(0, 0, 0, 0);
      return { from: start.getTime(), to: Date.now() };
    },
  },
  last6mo: {
    label: "Last 6 months",
    footerLabel: "last 6 months",
    getRange: () => {
      const start = new Date();
      start.setMonth(start.getMonth() - 6);
      start.setHours(0, 0, 0, 0);
      return { from: start.getTime(), to: Date.now() };
    },
  },
  thisYear: {
    label: "This year",
    footerLabel: "this year",
    getRange: () => {
      const start = new Date();
      start.setMonth(0, 1);
      start.setHours(0, 0, 0, 0);
      return { from: start.getTime(), to: Date.now() };
    },
  },
  lastYear: {
    label: "Last year",
    footerLabel: "last year",
    getRange: () => {
      const year = new Date().getFullYear() - 1;
      const start = new Date(year, 0, 1);
      const end = new Date(year, 11, 31, 23, 59, 59, 999);
      return { from: start.getTime(), to: end.getTime() };
    },
  },
};

const PRESET_ORDER: DatePreset[] = [
  "today",
  "yesterday",
  "last7d",
  "last14d",
  "thisMonth",
  "lastMonth",
  "last30d",
  "last90d",
  "last6mo",
  "thisYear",
  "lastYear",
];

const MAX_LABEL_LENGTH = 120;

function formatTimestamp(ts: number): string {
  return new Date(ts).toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDateTimeShort(datetimeStr: string): string {
  return new Date(datetimeStr).toLocaleString([], {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function truncate(text: string, maxLength: number): string {
  const singleLine = text.replace(/\n+/g, " ").trim();
  if (singleLine.length <= maxLength) return singleLine;
  return `${singleLine.slice(0, maxLength)}…`;
}

/** A midnight "to" bound means the user picked a day without a time, so include that whole day. */
function customRangeEnd(value: string): number {
  const end = new Date(value);
  if (end.getHours() === 0 && end.getMinutes() === 0) {
    end.setHours(23, 59, 59, 999);
  }
  return end.getTime();
}

export function MessageJumpPicker({
  open,
  onOpenChange,
  items,
  onJumpToMessage,
}: MessageJumpPickerProps) {
  // The body only mounts while the dialog is open, so every open starts with clean filter state.
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-message-jump-picker=""
        className="w-180 max-w-[90vw] gap-0 p-0"
        showCloseButton={false}
      >
        {open ? (
          <JumpPickerBody
            items={items}
            onJumpToMessage={onJumpToMessage}
            onOpenChange={onOpenChange}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function JumpPickerBody({
  items,
  onJumpToMessage,
  onOpenChange,
}: {
  items: ConversationItem[];
  onJumpToMessage: (id: string) => void;
  onOpenChange: (open: boolean) => void;
}) {
  const [query, setQuery] = useState("");
  const [activePreset, setActivePreset] = useState<DatePreset | null>(null);
  const [showCustom, setShowCustom] = useState(false);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  const entries = useMemo<JumpEntry[]>(() => {
    const result: JumpEntry[] = [];
    for (const item of items) {
      if (item.type === "user_message") {
        result.push({
          id: item.id,
          label: truncate(item.content, MAX_LABEL_LENGTH),
          fullText: item.content,
          timestamp: item.timestamp,
        });
      }
    }
    return result;
  }, [items]);

  const visibleEntries = useMemo(() => {
    let filtered = entries;

    if (activePreset !== null) {
      const { from, to } = DATE_PRESETS[activePreset].getRange();
      filtered = filtered.filter(
        (e) => e.timestamp >= from && e.timestamp <= to,
      );
    } else if (showCustom) {
      if (customFrom) {
        filtered = filtered.filter(
          (e) => e.timestamp >= new Date(customFrom).getTime(),
        );
      }
      if (customTo) {
        const end = customRangeEnd(customTo);
        filtered = filtered.filter((e) => e.timestamp <= end);
      }
    }

    const normalizedQuery = query.trim().toLowerCase();
    if (normalizedQuery) {
      filtered = filtered.filter((entry) =>
        entry.fullText.toLowerCase().includes(normalizedQuery),
      );
    }

    return filtered;
  }, [entries, query, activePreset, showCustom, customFrom, customTo]);

  const footerFilterLabel = useMemo((): string | null => {
    if (activePreset !== null) return DATE_PRESETS[activePreset].footerLabel;
    if (showCustom) {
      if (customFrom && customTo) {
        return `${formatDateTimeShort(customFrom)} – ${formatDateTimeShort(customTo)}`;
      }
      if (customFrom) return `after ${formatDateTimeShort(customFrom)}`;
      if (customTo) return `before ${formatDateTimeShort(customTo)}`;
    }
    return null;
  }, [activePreset, showCustom, customFrom, customTo]);

  const triggerLabel = useMemo((): string => {
    if (activePreset !== null) return DATE_PRESETS[activePreset].label;
    if (showCustom && (customFrom || customTo)) return "Custom";
    return "Filter";
  }, [activePreset, showCustom, customFrom, customTo]);

  const filterActive =
    activePreset !== null ||
    (showCustom && (customFrom !== "" || customTo !== ""));

  const handlePreset = useCallback((preset: DatePreset) => {
    setActivePreset((current) => (current === preset ? null : preset));
    setShowCustom(false);
    setCustomFrom("");
    setCustomTo("");
  }, []);

  const handleCustom = useCallback(() => {
    setActivePreset(null);
    setShowCustom(true);
  }, []);

  const clearCustom = useCallback(() => {
    setCustomFrom("");
    setCustomTo("");
    setShowCustom(false);
  }, []);

  const handleSelect = useCallback(
    (id: string | null) => {
      if (id === null) return;
      const entry = visibleEntries.find((e) => e.id === id);
      if (!entry) return;
      onJumpToMessage(entry.id);
      onOpenChange(false);
    },
    [visibleEntries, onJumpToMessage, onOpenChange],
  );

  return (
    <>
      <Autocomplete<JumpEntry>
        inline
        defaultOpen
        items={visibleEntries}
        filter={null}
        value={query}
        autoHighlight="always"
        onValueChange={(val, eventDetails) => {
          if (eventDetails.reason !== "input-change") return;
          if (typeof val === "string") {
            setQuery(val);
          }
        }}
      >
        <Flex align="center" gap="2" className="pt-2 pb-1">
          <div className="min-w-0 flex-1">
            <AutocompleteInput
              placeholder="Jump to message…"
              autoFocus
              showClear
            >
              <DropdownMenu>
                <DropdownMenuTrigger
                  render={
                    <button
                      type="button"
                      className={`flex cursor-pointer select-none items-center gap-1 rounded px-1.5 py-0.5 text-[11px] transition-colors ${
                        filterActive
                          ? "text-(--accent-9) hover:text-(--accent-10)"
                          : "text-(--gray-9) hover:text-(--gray-11)"
                      }`}
                    >
                      <FunnelSimple
                        size={12}
                        weight={filterActive ? "fill" : "regular"}
                      />
                      <span>{triggerLabel}</span>
                    </button>
                  }
                />
                <DropdownMenuContent
                  align="end"
                  side="bottom"
                  sideOffset={8}
                  className="w-44"
                >
                  <div className="scrollbar-hide max-h-[152px] overflow-y-auto">
                    {PRESET_ORDER.map((preset) => (
                      <DropdownMenuItem
                        key={preset}
                        onClick={() => handlePreset(preset)}
                        className="flex items-center justify-between"
                      >
                        <span>{DATE_PRESETS[preset].label}</span>
                        {activePreset === preset && (
                          <Check size={12} className="text-(--accent-9)" />
                        )}
                      </DropdownMenuItem>
                    ))}
                  </div>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={handleCustom}>
                    Custom range…
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </AutocompleteInput>
          </div>
        </Flex>

        {showCustom && (
          <Flex
            align="center"
            gap="2"
            className="border-(--gray-4) border-t px-3 py-1.5"
          >
            <input
              type="datetime-local"
              aria-label="Filter from date"
              value={customFrom}
              max={customTo || undefined}
              onChange={(e) => setCustomFrom(e.target.value)}
              className="h-[22px] min-w-0 flex-1 rounded-(--radius-1) border border-(--gray-a5) bg-(--gray-a2) px-1.5 text-(--gray-12) text-[12px] tabular-nums outline-none focus:border-(--accent-8)"
            />
            <span className="shrink-0 text-(--gray-10) text-[11px]">–</span>
            <input
              type="datetime-local"
              aria-label="Filter to date"
              value={customTo}
              min={customFrom || undefined}
              onChange={(e) => setCustomTo(e.target.value)}
              className="h-[22px] min-w-0 flex-1 rounded-(--radius-1) border border-(--gray-a5) bg-(--gray-a2) px-1.5 text-(--gray-12) text-[12px] tabular-nums outline-none focus:border-(--accent-8)"
            />
            <button
              type="button"
              onClick={clearCustom}
              className="shrink-0 cursor-pointer text-(--gray-10) transition-colors hover:text-(--gray-12)"
              aria-label="Clear date filter"
            >
              <X size={11} weight="bold" />
            </button>
          </Flex>
        )}

        <AutocompleteList className="max-h-[55vh] pt-1">
          {(entry: JumpEntry) => (
            <AutocompleteItem
              key={entry.id}
              value={entry.id}
              onClick={() => handleSelect(entry.id)}
              className="group/entry h-auto! min-h-7 py-1.5 text-left"
            >
              <ChatText size={14} className="shrink-0 text-(--gray-11)" />
              <span
                className="min-w-0 flex-1 truncate text-[13px]"
                title={entry.fullText}
              >
                {entry.label}
              </span>
              <span className="shrink-0 text-(--gray-10) text-[11px] tabular-nums opacity-0 transition-opacity group-hover/entry:opacity-100">
                {formatTimestamp(entry.timestamp)}
              </span>
            </AutocompleteItem>
          )}
        </AutocompleteList>
      </Autocomplete>
      <Flex
        align="center"
        justify="between"
        className="border-(--gray-5) border-t px-3 py-2"
      >
        <span className="text-(--gray-11) text-[12px]">
          {visibleEntries.length}{" "}
          {visibleEntries.length === 1 ? "message" : "messages"}
          {footerFilterLabel !== null && (
            <span className="ml-1 text-(--gray-10)">({footerFilterLabel})</span>
          )}
        </span>
        <CommandKeyHints />
      </Flex>
    </>
  );
}
