import {
  type CanvasListSettings,
  DEFAULT_CANVAS_LIST_GROUPING,
  DEFAULT_CANVAS_LIST_SETTINGS,
  DEFAULT_CANVAS_LIST_SORT,
  hasCustomizedCanvasList,
} from "@posthog/core/canvas/canvasListService";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuSeparator,
} from "@posthog/quill";
import { CanvasFilterMultiSelectSubmenu } from "@posthog/ui/features/canvas/components/CanvasFilterMultiSelectSubmenu";
import {
  type CanvasFilterOption,
  type CanvasMultiSelectOption,
  summarizeCreatorSelection,
  summarizeSpaceSelection,
} from "@posthog/ui/features/canvas/components/canvasFilterSelection";
import {
  FilterClearItem,
  FilterMenuTrigger,
  FilterRadioSubMenu,
} from "@posthog/ui/primitives/FilterMenu";
import type { ReactElement } from "react";

const SORT_OPTIONS: readonly CanvasFilterOption<CanvasListSettings["sort"]>[] =
  [
    { value: "recently_viewed", label: "Last viewed" },
    { value: "created_by", label: "Created by" },
  ];

const GROUPING_OPTIONS: readonly CanvasFilterOption<
  CanvasListSettings["grouping"]
>[] = [
  { value: "none", label: "None" },
  { value: "space", label: "Space" },
  { value: "date", label: "Date" },
];

export function CanvasFilterMenu({
  spaceOptions,
  creatorOptions,
  createdByDisabled,
  settings,
  onChange,
}: {
  spaceOptions: readonly CanvasMultiSelectOption[];
  creatorOptions: readonly CanvasMultiSelectOption[];
  createdByDisabled: boolean;
  settings: CanvasListSettings;
  onChange: (settings: CanvasListSettings) => void;
}): ReactElement {
  const active = hasCustomizedCanvasList(settings);
  const updateSetting = <Key extends keyof CanvasListSettings>(
    key: Key,
    value: CanvasListSettings[Key],
  ): void => onChange({ ...settings, [key]: value });

  return (
    <DropdownMenu>
      <FilterMenuTrigger
        active={active}
        label="Filter canvases"
        dataAttr="canvas-list-filter"
        size="icon-xs"
      />
      <DropdownMenuContent
        align="end"
        side="bottom"
        sideOffset={6}
        className="w-64"
        aria-label="Filter canvases"
      >
        <FilterRadioSubMenu
          label="Group by"
          options={GROUPING_OPTIONS}
          value={settings.grouping}
          defaultValue={DEFAULT_CANVAS_LIST_GROUPING}
          onChange={(grouping) => updateSetting("grouping", grouping)}
        />
        <FilterRadioSubMenu
          label="Sort by"
          options={SORT_OPTIONS}
          value={settings.sort}
          defaultValue={DEFAULT_CANVAS_LIST_SORT}
          onChange={(sort) => updateSetting("sort", sort)}
        />
        <DropdownMenuSeparator />
        <CanvasFilterMultiSelectSubmenu
          label="Space"
          summary={summarizeSpaceSelection(spaceOptions, settings.spaceIds)}
          options={spaceOptions}
          values={settings.spaceIds}
          onChange={(spaceIds) => updateSetting("spaceIds", spaceIds)}
          searchPlaceholder="Search spaces…"
          emptyLabel="No spaces found."
        />
        <CanvasFilterMultiSelectSubmenu
          label="Created by"
          summary={
            createdByDisabled
              ? "Me"
              : summarizeCreatorSelection(creatorOptions, settings.creatorUuids)
          }
          options={creatorOptions}
          values={settings.creatorUuids}
          onChange={(creatorUuids) =>
            updateSetting("creatorUuids", creatorUuids)
          }
          searchPlaceholder="Search users…"
          emptyLabel="No users found."
          disabled={createdByDisabled}
        />
        <FilterClearItem
          active={active}
          dataAttr="clear-canvas-list-filters"
          onClear={() => onChange(DEFAULT_CANVAS_LIST_SETTINGS)}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
