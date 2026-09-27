import {
  DropdownMenu,
  DropdownMenuContent,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import { sourceIcon } from "@posthog/ui/features/canvas/components/CommentThreadGroups";
import type { ThreadSourceOption } from "@posthog/ui/features/canvas/components/taskCommentThreads";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import {
  FilterMenuTrigger,
  type FilterOption,
  FilterRadioSubMenu,
} from "@posthog/ui/primitives/FilterMenu";
import type { ReactElement, ReactNode } from "react";

export const ALL_SOURCES = "all";
const SOURCE_SEARCH_THRESHOLD = 8;

export type CommentStateFilter = "open" | "resolved";

export function CommentListHeader({
  stateFilter,
  openCount,
  resolvedCount,
  onStateFilterChange,
  sourceFilter,
}: {
  stateFilter: CommentStateFilter;
  openCount: number;
  resolvedCount: number;
  onStateFilterChange: (filter: CommentStateFilter) => void;
  sourceFilter?: ReactNode;
}): ReactElement {
  return (
    <ChromeBar inset="even" actions={sourceFilter}>
      <Tabs
        value={stateFilter}
        onValueChange={(value: string) =>
          onStateFilterChange(value as CommentStateFilter)
        }
      >
        <TabsList aria-label="Filter comments">
          <TabsTrigger value="open">Open {openCount}</TabsTrigger>
          <TabsTrigger value="resolved">Resolved {resolvedCount}</TabsTrigger>
        </TabsList>
      </Tabs>
    </ChromeBar>
  );
}

export function CommentSourceFilter({
  value,
  valueLabel,
  options,
  onChange,
}: {
  value: string;
  valueLabel: string;
  options: readonly ThreadSourceOption[];
  onChange: (value: string) => void;
}): ReactElement {
  const filterOptions: FilterOption<string>[] = [
    { value: ALL_SOURCES, label: "All sources" },
    ...options.map((option) => ({
      value: option.key,
      label: option.label,
      icon: sourceIcon(option.kind, option.label),
    })),
  ];
  return (
    <DropdownMenu>
      <FilterMenuTrigger
        active={value !== ALL_SOURCES}
        label="Filter by source"
        dataAttr="task-comments-source-filter"
      />
      <DropdownMenuContent
        align="end"
        side="bottom"
        sideOffset={6}
        className="w-64"
        aria-label="Filter by source"
      >
        <FilterRadioSubMenu
          label="Source"
          options={filterOptions}
          value={value}
          defaultValue={ALL_SOURCES}
          valueLabel={valueLabel}
          onChange={onChange}
          searchPlaceholder={
            options.length > SOURCE_SEARCH_THRESHOLD
              ? "Search sources…"
              : undefined
          }
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
