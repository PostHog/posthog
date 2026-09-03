import {
  Combobox,
  ComboboxCollection,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@posthog/quill";
import type { CanvasMultiSelectOption } from "@posthog/ui/features/canvas/components/canvasFilterSelection";
import type { ReactElement, SyntheticEvent } from "react";

const DEFAULT_OPTION_KEY = "__canvas_filter_default__";

function stopPropagation(event: SyntheticEvent): void {
  event.stopPropagation();
}

export function CanvasFilterMultiSelectSubmenu({
  label,
  summary,
  options,
  values,
  onChange,
  searchPlaceholder,
  emptyLabel,
  disabled = false,
}: {
  label: string;
  summary: string;
  options: readonly CanvasMultiSelectOption[];
  values: readonly string[];
  onChange: (values: string[]) => void;
  searchPlaceholder: string;
  emptyLabel: string;
  disabled?: boolean;
}): ReactElement {
  const selectedValues = new Set(values);
  const selectedOptions = options.filter(
    (option) => option.value !== null && selectedValues.has(option.value),
  );
  const defaultOption = options.find((option) => option.value === null);
  const comboboxValue =
    selectedOptions.length === 0 && defaultOption
      ? [defaultOption]
      : selectedOptions;

  const updateSelection = (nextOptions: CanvasMultiSelectOption[]): void => {
    const defaultSelected = nextOptions.some((option) => option.value === null);
    const nextValues = nextOptions.flatMap((option) =>
      option.value === null ? [] : [option.value],
    );
    if (defaultSelected) {
      onChange(values.length === 0 ? nextValues : []);
      return;
    }
    onChange(nextValues);
  };

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger className="pr-1" disabled={disabled}>
        <span>{label}</span>
        <span
          title={summary}
          className={
            values.length === 0
              ? "min-w-0 flex-1 truncate pl-4 text-right text-muted-foreground/80"
              : "min-w-0 flex-1 truncate pl-4 text-right text-primary"
          }
        >
          {summary}
        </span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="w-64 [&>div]:overflow-hidden [&>div]:p-0">
        <Combobox<CanvasMultiSelectOption, true>
          multiple
          autoHighlight
          items={options}
          value={comboboxValue}
          onValueChange={(nextOptions) => updateSelection(nextOptions ?? [])}
          itemToStringLabel={(option) =>
            `${option.label} ${option.searchLabel ?? ""}`
          }
          itemToStringValue={(option) => option.value ?? DEFAULT_OPTION_KEY}
        >
          <div className="p-1">
            <ComboboxInput
              autoFocus
              showTrigger={false}
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder}
              className="w-full"
              onClick={stopPropagation}
              onKeyDown={stopPropagation}
            />
          </div>
          <ComboboxList className="group/combobox-list max-h-72 border-border border-t">
            <ComboboxCollection>
              {(option: CanvasMultiSelectOption) => (
                <ComboboxItem
                  key={option.value ?? "default"}
                  value={option}
                  className="ps-7"
                  onClick={stopPropagation}
                >
                  {option.icon}
                  {option.label}
                </ComboboxItem>
              )}
            </ComboboxCollection>
            <ComboboxEmpty className="group-data-empty/combobox-list:flex">
              {emptyLabel}
            </ComboboxEmpty>
          </ComboboxList>
        </Combobox>
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
