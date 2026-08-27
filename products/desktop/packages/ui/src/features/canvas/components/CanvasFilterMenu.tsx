import { FunnelSimple as FunnelSimpleIcon } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { CanvasFilterMultiSelectSubmenu } from "@posthog/ui/features/canvas/components/CanvasFilterMultiSelectSubmenu";
import { CanvasFilterRadioSubmenu } from "@posthog/ui/features/canvas/components/CanvasFilterRadioSubmenu";
import {
  type CanvasFilterOption,
  summarizeCreatorSelection,
  summarizeSpaceSelection,
} from "@posthog/ui/features/canvas/components/canvasFilterSelection";
import {
  type CanvasListGrouping,
  type CanvasListSort,
  DEFAULT_CANVAS_LIST_GROUPING,
  DEFAULT_CANVAS_LIST_SORT,
} from "@posthog/ui/features/canvas/components/canvasList";
import type { ReactElement } from "react";

const SORT_OPTIONS: readonly CanvasFilterOption[] = [
  { value: "recently_viewed", label: "Last viewed" },
  { value: "created_by", label: "Created by" },
];

const GROUPING_OPTIONS: readonly CanvasFilterOption[] = [
  { value: "none", label: "None" },
  { value: "space", label: "Space" },
  { value: "date", label: "Date" },
];

export function CanvasFilterMenu({
  spaceOptions,
  spaceIds,
  onSpaceChange,
  creatorOptions,
  creatorUuids,
  onCreatorChange,
  sort,
  onSortChange,
  grouping,
  onGroupingChange,
  onClear,
  active,
}: {
  spaceOptions: readonly CanvasFilterOption[];
  spaceIds: readonly string[];
  onSpaceChange: (spaceIds: string[]) => void;
  creatorOptions: readonly CanvasFilterOption[];
  creatorUuids: readonly string[];
  onCreatorChange: (creatorUuids: string[]) => void;
  sort: CanvasListSort;
  onSortChange: (sort: CanvasListSort) => void;
  grouping: CanvasListGrouping;
  onGroupingChange: (grouping: CanvasListGrouping) => void;
  onClear: () => void;
  active: boolean;
}): ReactElement {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="default"
            size="icon-xs"
            aria-label="Filter canvases"
            data-attr="canvas-list-filter"
            className="relative"
          >
            <FunnelSimpleIcon />
            {active && (
              <span
                aria-hidden
                className="absolute top-0 right-0 size-1.5 rounded-full bg-primary"
              />
            )}
          </Button>
        }
      />
      <DropdownMenuContent
        align="end"
        side="bottom"
        sideOffset={6}
        className="w-64"
        aria-label="Filter canvases"
      >
        <CanvasFilterRadioSubmenu
          label="Group by"
          options={GROUPING_OPTIONS}
          value={grouping}
          defaultValue={DEFAULT_CANVAS_LIST_GROUPING}
          onChange={(value) => onGroupingChange(value as CanvasListGrouping)}
        />
        <CanvasFilterRadioSubmenu
          label="Sort by"
          options={SORT_OPTIONS}
          value={sort}
          defaultValue={DEFAULT_CANVAS_LIST_SORT}
          onChange={(value) => onSortChange(value as CanvasListSort)}
        />
        <DropdownMenuSeparator />
        <CanvasFilterMultiSelectSubmenu
          label="Space"
          summary={summarizeSpaceSelection(spaceOptions, spaceIds)}
          options={spaceOptions}
          values={spaceIds}
          onChange={onSpaceChange}
          searchPlaceholder="Search spaces…"
          emptyLabel="No spaces found."
        />
        <CanvasFilterMultiSelectSubmenu
          label="Created by"
          summary={summarizeCreatorSelection(creatorOptions, creatorUuids)}
          options={creatorOptions}
          values={creatorUuids}
          onChange={onCreatorChange}
          searchPlaceholder="Search users…"
          emptyLabel="No users found."
        />
        {active && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              data-attr="clear-canvas-list-filters"
              variant="destructive"
              onClick={onClear}
            >
              Clear filters
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
