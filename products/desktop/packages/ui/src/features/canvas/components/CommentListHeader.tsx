import {
  DropdownMenu,
  DropdownMenuContent,
  Tabs,
  TabsList,
  TabsTrigger,
} from "@posthog/quill";
import { SourceIcon } from "@posthog/ui/features/canvas/components/CommentThreadGroups";
import type { ThreadSourceOption } from "@posthog/ui/features/canvas/components/taskCommentThreads";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import {
  FilterMenuTrigger,
  FilterRadioSubMenu,
} from "@posthog/ui/primitives/FilterMenu";
import type { ReactElement } from "react";

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
  sourceFilter?: {
    value: string;
    valueLabel: string;
    options: readonly ThreadSourceOption[];
    onChange: (value: string) => void;
  };
}): ReactElement {
  return (
    <ChromeBar
      inset="even"
      actions={
        sourceFilter && (
          <DropdownMenu>
            <FilterMenuTrigger
              active={sourceFilter.value !== ALL_SOURCES}
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
                options={[
                  { value: ALL_SOURCES, label: "All sources" },
                  ...sourceFilter.options.map((option) => ({
                    value: option.key,
                    label: option.label,
                    icon: (
                      <SourceIcon kind={option.kind} label={option.label} />
                    ),
                  })),
                ]}
                value={sourceFilter.value}
                defaultValue={ALL_SOURCES}
                valueLabel={sourceFilter.valueLabel}
                onChange={sourceFilter.onChange}
                searchPlaceholder={
                  sourceFilter.options.length > SOURCE_SEARCH_THRESHOLD
                    ? "Search sources…"
                    : undefined
                }
              />
            </DropdownMenuContent>
          </DropdownMenu>
        )
      }
    >
      <Tabs
        className="self-stretch"
        value={stateFilter}
        onValueChange={(value: string) =>
          onStateFilterChange(value as CommentStateFilter)
        }
      >
        <TabsList
          variant="line"
          className="!h-full"
          aria-label="Filter comments"
        >
          <TabsTrigger value="open">
            Open
            <span className="text-muted-foreground tabular-nums">
              {openCount}
            </span>
          </TabsTrigger>
          <TabsTrigger value="resolved">
            Resolved
            <span className="text-muted-foreground tabular-nums">
              {resolvedCount}
            </span>
          </TabsTrigger>
        </TabsList>
      </Tabs>
    </ChromeBar>
  );
}
