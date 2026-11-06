import { BlueprintIcon } from "@phosphor-icons/react";
import type { CanvasListViewModel } from "@posthog/core/canvas/canvasListService";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import {
  Autocomplete,
  AutocompleteItem,
  AutocompleteList,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  MenuLabel,
} from "@posthog/quill";
import { formatAbsoluteDateTime, formatRelativeAge } from "@posthog/shared";
import { LoadingState } from "@posthog/ui/primitives/LoadingState";
import { defaultRangeExtractor, useVirtualizer } from "@tanstack/react-virtual";
import {
  type ReactElement,
  type ReactNode,
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { iconForTemplate } from "./canvasTemplateIcon";
import { SidebarSearchHeader } from "./SidebarSearchHeader";

interface CanvasListProps {
  viewModel: CanvasListViewModel;
  lastViewedAtByCanvasId: Readonly<Record<string, number>>;
  selectedId?: string;
  query: string;
  setQuery: (query: string) => void;
  open: (canvas: DashboardRecord) => void;
  isLoading?: boolean;
  actions?: ReactNode;
  className?: string;
}

type CanvasRow =
  | { key: string; label: string; canvas?: never; optionIndex?: never }
  | {
      key: string;
      canvas: DashboardRecord;
      optionIndex: number;
      label?: never;
    };

export function CanvasList({
  viewModel,
  lastViewedAtByCanvasId,
  selectedId,
  query,
  setQuery,
  open,
  isLoading,
  actions,
  className,
}: CanvasListProps): ReactElement {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [highlightedId, setHighlightedId] = useState<string>();
  const { rows, optionValues, rowIndexById } = useMemo(() => {
    const rows: CanvasRow[] = [];
    const optionValues: string[] = [];
    const rowIndexById = new Map<string, number>();
    for (const section of viewModel.sections) {
      if (section.label)
        rows.push({ key: `heading:${section.key}`, label: section.label });
      for (const canvas of section.canvases) {
        rowIndexById.set(canvas.id, rows.length);
        rows.push({ key: canvas.id, canvas, optionIndex: optionValues.length });
        optionValues.push(canvas.id);
      }
    }
    return { rows, optionValues, rowIndexById };
  }, [viewModel.sections]);
  const virtualized = optionValues.length > 40 && !isLoading;
  const highlightedIndex =
    highlightedId === undefined ? undefined : rowIndexById.get(highlightedId);
  const virtualizer = useVirtualizer({
    count: rows.length,
    enabled: virtualized,
    getScrollElement: () => viewportRef.current,
    estimateSize: (index) => (rows[index].canvas ? 46 : 26),
    getItemKey: useCallback((index: number) => rows[index].key, [rows]),
    gap: 1,
    measureElement: (element) => element.getBoundingClientRect().height,
    overscan: 4,
    rangeExtractor: useCallback(
      (range: Parameters<typeof defaultRangeExtractor>[0]) => {
        const indexes = defaultRangeExtractor(range);
        // Keep the keyboard target mounted if the pointer scrolls it out of view.
        if (
          highlightedIndex !== undefined &&
          !indexes.includes(highlightedIndex)
        ) {
          indexes.push(highlightedIndex);
          indexes.sort((a, b) => a - b);
        }
        return indexes;
      },
      [highlightedIndex],
    ),
  });
  // The view model gets a new identity on every canvas refetch, so the reset
  // keys on the inputs that actually reorder the list.
  const filterKey = JSON.stringify([query, viewModel.settings]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: filterKey is the trigger, not a body dependency
  useLayoutEffect(() => {
    if (virtualized) virtualizer.scrollToOffset(0);
    else if (viewportRef.current) viewportRef.current.scrollTop = 0;
  }, [filterKey, virtualized, virtualizer]);
  const renderRow = (row: CanvasRow): ReactElement => {
    if (!row.canvas) return <MenuLabel>{row.label}</MenuLabel>;
    const canvas = row.canvas;
    const lastViewedAt = lastViewedAtByCanvasId[canvas.id];
    const lastViewedLabel = lastViewedAt
      ? `Last viewed ${formatRelativeAge(lastViewedAt)}`
      : "Not viewed yet";
    const lastViewedTitle = lastViewedAt
      ? `Last viewed ${formatAbsoluteDateTime(lastViewedAt)}`
      : lastViewedLabel;
    return (
      <AutocompleteItem
        value={canvas.id}
        index={virtualized ? row.optionIndex : undefined}
        // Only the mounted rows reach the accessibility tree, so screen readers
        // need the position within the whole list stated outright.
        aria-posinset={virtualized ? row.optionIndex + 1 : undefined}
        aria-setsize={virtualized ? optionValues.length : undefined}
        nativeButton
        className={cn(
          "h-auto w-full items-start py-1.5 text-left ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0 [&>span]:w-full [&>span]:items-start [&>span]:gap-2",
          canvas.id === selectedId && "bg-fill-selected",
        )}
        onClick={() => open(canvas)}
      >
        {iconForTemplate(canvas.templateId, { size: 14 })}
        <span className="min-w-0">
          <span className="block truncate text-[13px]">{canvas.name}</span>
          <span
            className="block truncate text-muted-foreground text-xxs"
            title={lastViewedTitle}
          >
            {canvas.createdBy ?? "Unknown"} · {lastViewedLabel}
          </span>
        </span>
      </AutocompleteItem>
    );
  };
  return (
    <Autocomplete<string>
      inline
      open
      value={query}
      items={optionValues}
      filter={null}
      virtualized={virtualized}
      onItemHighlighted={(value, details) => {
        setHighlightedId(value);
        const index = value === undefined ? undefined : rowIndexById.get(value);
        if (
          virtualized &&
          index !== undefined &&
          details.reason === "keyboard"
        ) {
          virtualizer.scrollToIndex(index, { align: "auto" });
        }
      }}
      onValueChange={(value, eventDetails) => {
        if (
          eventDetails.reason === "input-change" &&
          typeof value === "string"
        ) {
          setQuery(value);
        }
      }}
    >
      <div className={cn("flex min-h-0 flex-col", className)}>
        <SidebarSearchHeader
          title="Canvases"
          query={query}
          placeholder="Search canvases…"
          searchLabel="Search canvases"
          onClear={() => setQuery("")}
          actions={actions}
        />
        <AutocompleteList
          ref={viewportRef}
          className="sidebar-autocomplete-tree scroll-mask-8 !max-h-none !p-1.5 min-h-0 flex-1 overflow-y-auto"
        >
          {isLoading ? (
            <LoadingState className="py-10" />
          ) : viewModel.canvases.length === 0 ? (
            <Empty className="border-0 py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <BlueprintIcon />
                </EmptyMedia>
                <EmptyTitle>No canvases match</EmptyTitle>
                <EmptyDescription>
                  Try another search or filter.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : virtualized ? (
            <div
              className="relative w-full"
              style={{ height: virtualizer.getTotalSize() }}
            >
              {virtualizer.getVirtualItems().map((item) => (
                <div
                  key={item.key}
                  ref={virtualizer.measureElement}
                  data-index={item.index}
                  className="absolute top-0 left-0 flex w-full flex-col"
                  style={{ transform: `translateY(${item.start}px)` }}
                >
                  {renderRow(rows[item.index])}
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col gap-px">
              {rows.map((row) => (
                <div className="flex flex-col" key={row.key}>
                  {renderRow(row)}
                </div>
              ))}
            </div>
          )}
        </AutocompleteList>
      </div>
    </Autocomplete>
  );
}
