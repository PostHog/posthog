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
import { eventLabel } from "@posthog/ui/features/canvas/blocks/blocksFormat";
import {
  TOP_EVENT_PROPERTIES_HOGQL,
  TOP_EVENTS_HOGQL,
  useHogqlRows,
  useSavedInsights,
} from "@posthog/ui/features/canvas/blocks/pickerQueries";
import { useCallback, useMemo, useRef, useState } from "react";

const CUSTOM_PREFIX = "__custom__:";
const NONE_VALUE = "__none__";

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
  format = (option) => option,
}: SearchPickerProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
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
  const { data, isLoading } = useHogqlRows(TOP_EVENTS_HOGQL);
  const options = useMemo(
    () => (data ?? []).map((row) => String(row[0])),
    [data],
  );
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
  const { data, isLoading } = useHogqlRows(TOP_EVENT_PROPERTIES_HOGQL);
  const options = useMemo(
    () => (data ?? []).map((row) => String(row[0])),
    [data],
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
  const { data, isLoading } = useSavedInsights();
  const names = useMemo(
    () =>
      new Map((data ?? []).map((insight) => [insight.shortId, insight.name])),
    [data],
  );
  const options = useMemo(() => [...names.keys()], [names]);
  const format = useCallback(
    (shortId: string) => names.get(shortId) ?? shortId,
    [names],
  );
  return (
    <SearchPicker
      value={value}
      onChange={onChange}
      options={options}
      loading={isLoading}
      placeholder="Pick a saved insight"
      searchPlaceholder="Search insights…"
      ariaLabel="Insight"
      format={format}
    />
  );
}
