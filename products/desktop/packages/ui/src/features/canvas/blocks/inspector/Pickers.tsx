import { CaretDown, Lightning } from "@phosphor-icons/react";
import { propertyDisplayName } from "@posthog/core/canvas/blockLibrary/propertyNames";
import {
  Button,
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
} from "@posthog/quill";
import {
  TOP_EVENT_PROPERTIES_HOGQL,
  TOP_EVENTS_HOGQL,
  useSavedInsights,
  useTopValues,
} from "@posthog/ui/features/canvas/blocks/pickerQueries";
import { useDebouncedValue } from "@posthog/ui/primitives/hooks/useDebouncedValue";
import { useCallback, useMemo, useRef, useState } from "react";

const CUSTOM_PREFIX = "__custom__:";
const NONE_VALUE = "__none__";

function eventLabel(event: string): string {
  const known: Record<string, string> = {
    $pageview: "Pageview",
    $pageleave: "Pageleave",
    $autocapture: "Autocapture",
    $screen: "Screen",
    $identify: "Identify",
    $exception: "Exception",
    $web_vitals: "Web vitals",
    $feature_flag_called: "Feature flag called",
    $groupidentify: "Group identify",
    $set: "Set person properties",
  };
  if (known[event]) return known[event];
  if (!event.startsWith("$")) return event;
  const words = event.slice(1).replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function sameText(value: string): string {
  return value;
}

interface SearchPickerProps {
  value: string | null;
  onChange: (value: string | null) => void;
  options: string[];
  loading: boolean;
  placeholder: string;
  searchPlaceholder: string;
  ariaLabel: string;
  allowNone?: boolean;
  noneLabel?: string;
  format?: (value: string) => string;
  onSearchChange?: (search: string) => void;
}

function SearchPicker({
  value,
  onChange,
  options,
  loading,
  placeholder,
  searchPlaceholder,
  ariaLabel,
  allowNone,
  noneLabel = "None",
  format = sameText,
  onSearchChange,
}: SearchPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearchState] = useState("");
  const setSearch = (next: string) => {
    setSearchState(next);
    onSearchChange?.(next);
  };
  const anchorRef = useRef<HTMLDivElement>(null);
  const items = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const base =
      value && !options.includes(value) ? [value, ...options] : options;
    const matches = needle
      ? base.filter(
          (option) =>
            option.toLowerCase().includes(needle) ||
            format(option).toLowerCase().includes(needle),
        )
      : base;
    const exact = base.some((option) => option.toLowerCase() === needle);
    const custom = needle && !exact ? [`${CUSTOM_PREFIX}${search.trim()}`] : [];
    return [
      ...(allowNone && !needle ? [NONE_VALUE] : []),
      ...matches.slice(0, 150),
      ...custom,
    ];
  }, [search, options, value, allowNone, format]);

  const choose = (next: string | null) => {
    setOpen(false);
    setSearch("");
    if (next === null) return;
    if (next === NONE_VALUE) {
      onChange(null);
      return;
    }
    onChange(
      next.startsWith(CUSTOM_PREFIX) ? next.slice(CUSTOM_PREFIX.length) : next,
    );
  };

  return (
    <div ref={anchorRef} className="w-full">
      <Combobox
        items={items}
        filter={null}
        value={value ?? NONE_VALUE}
        onValueChange={(next) => choose(next as string | null)}
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setSearch("");
        }}
        inputValue={search}
        onInputValueChange={(next) => setSearch(next ?? "")}
        modal={false}
      >
        <ComboboxTrigger
          render={
            <Button
              variant="outline"
              size="sm"
              className="w-full min-w-0 justify-between"
              aria-label={ariaLabel}
            >
              <span className="min-w-0 truncate">
                {value ? format(value) : allowNone ? noneLabel : placeholder}
              </span>
              <CaretDown
                size={10}
                weight="bold"
                className="shrink-0 opacity-60"
              />
            </Button>
          }
        />
        <ComboboxContent
          anchor={anchorRef}
          side="bottom"
          align="start"
          sideOffset={4}
          className="w-[260px]"
        >
          <ComboboxInput placeholder={searchPlaceholder} showTrigger={false} />
          <ComboboxEmpty>
            {loading ? "Loading…" : "Nothing found"}
          </ComboboxEmpty>
          <ComboboxList className="max-h-[280px]">
            {(item: string) => {
              if (item === NONE_VALUE) {
                return (
                  <ComboboxItem key={item} value={item}>
                    <span className="text-muted-foreground">{noneLabel}</span>
                  </ComboboxItem>
                );
              }
              if (item.startsWith(CUSTOM_PREFIX)) {
                const raw = item.slice(CUSTOM_PREFIX.length);
                return (
                  <ComboboxItem key={item} value={item}>
                    <Lightning size={12} className="shrink-0" />
                    <span className="min-w-0 truncate">Use “{raw}”</span>
                  </ComboboxItem>
                );
              }
              return (
                <ComboboxItem key={item} value={item} title={item}>
                  <span className="min-w-0 flex-1 truncate">
                    {format(item)}
                  </span>
                  {format(item) !== item ? (
                    <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                      {item}
                    </span>
                  ) : null}
                </ComboboxItem>
              );
            }}
          </ComboboxList>
        </ComboboxContent>
      </Combobox>
    </div>
  );
}

export function EventPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const { data: options = [], isLoading } = useTopValues(TOP_EVENTS_HOGQL);
  return (
    <SearchPicker
      value={value}
      onChange={(next) => {
        if (next) onChange(next);
      }}
      options={options}
      loading={isLoading}
      placeholder="Pick an event"
      searchPlaceholder="Search events…"
      ariaLabel="Event"
      format={eventLabel}
    />
  );
}

export function PropertyPicker({
  value,
  onChange,
  allowNone,
  noneLabel,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  allowNone?: boolean;
  noneLabel?: string;
}) {
  const { data: options = [], isLoading } = useTopValues(
    TOP_EVENT_PROPERTIES_HOGQL,
  );
  return (
    <SearchPicker
      value={value}
      onChange={onChange}
      options={options}
      loading={isLoading}
      placeholder="Pick a property"
      searchPlaceholder="Search properties…"
      ariaLabel="Property"
      format={propertyDisplayName}
      allowNone={allowNone}
      noneLabel={noneLabel}
    />
  );
}

export function InsightPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const [search, setSearch] = useState("");
  const [picked, setPicked] = useState<{ shortId: string; name: string }>();
  const { data, isLoading } = useSavedInsights(
    useDebouncedValue(search, 250).debounced,
  );
  const names = useMemo(
    () =>
      new Map([
        ...(picked ? [[picked.shortId, picked.name] as const] : []),
        ...(data ?? []).map(
          (insight) => [insight.shortId, insight.name] as const,
        ),
      ]),
    [data, picked],
  );
  const options = useMemo(
    () => (data ?? []).map((insight) => insight.shortId),
    [data],
  );
  const format = useCallback(
    (shortId: string) => names.get(shortId) ?? shortId,
    [names],
  );
  const choose = (next: string | null) => {
    const name = next ? names.get(next) : undefined;
    if (next && name) setPicked({ shortId: next, name });
    onChange(next);
  };
  return (
    <SearchPicker
      value={value}
      onChange={choose}
      options={options}
      loading={isLoading}
      placeholder="Pick a saved insight"
      searchPlaceholder="Search insights…"
      ariaLabel="Insight"
      format={format}
      onSearchChange={setSearch}
    />
  );
}
