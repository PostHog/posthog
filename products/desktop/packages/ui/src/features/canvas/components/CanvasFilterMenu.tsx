import { FunnelSimple as FunnelSimpleIcon } from "@phosphor-icons/react";
import {
  type CanvasListSettings,
  DEFAULT_CANVAS_LIST_GROUPING,
  DEFAULT_CANVAS_LIST_SETTINGS,
  DEFAULT_CANVAS_LIST_SORT,
  hasCustomizedCanvasList,
} from "@posthog/core/canvas/canvasListService";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { CanvasFilterMultiSelectSubmenu } from "@posthog/ui/features/canvas/components/CanvasFilterMultiSelectSubmenu";
import {
  type CanvasFilterOption,
  type CanvasMultiSelectOption,
  summarizeCreatorSelection,
  summarizeSpaceSelection,
} from "@posthog/ui/features/canvas/components/canvasFilterSelection";
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

function RadioSubmenu<Value extends string>({
  label,
  options,
  value,
  defaultValue,
  onChange,
}: {
  label: string;
  options: readonly CanvasFilterOption<Value>[];
  value: Value;
  defaultValue: Value;
  onChange: (value: Value) => void;
}): ReactElement {
  const selected =
    options.find((option) => option.value === value)?.label ?? "None";

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger className="pr-1">
        <span>{label}</span>
        <span
          title={selected}
          className={cn(
            "min-w-0 flex-1 truncate pl-4 text-right",
            value === defaultValue
              ? "text-muted-foreground/80"
              : "text-primary",
          )}
        >
          {selected}
        </span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(nextValue) => onChange(nextValue as Value)}
        >
          {options.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              {option.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

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
        <RadioSubmenu
          label="Group by"
          options={GROUPING_OPTIONS}
          value={settings.grouping}
          defaultValue={DEFAULT_CANVAS_LIST_GROUPING}
          onChange={(grouping) => updateSetting("grouping", grouping)}
        />
        <RadioSubmenu
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
        {active && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              data-attr="clear-canvas-list-filters"
              variant="destructive"
              onClick={() => onChange(DEFAULT_CANVAS_LIST_SETTINGS)}
            >
              Clear filters
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
