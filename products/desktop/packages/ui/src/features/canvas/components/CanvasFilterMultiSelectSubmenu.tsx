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
import type { CanvasFilterOption } from "@posthog/ui/features/canvas/components/canvasFilterSelection";
import type { ReactElement, SyntheticEvent } from "react";

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
}: {
  label: string;
  summary: string;
  options: readonly CanvasFilterOption[];
  values: readonly string[];
  onChange: (values: string[]) => void;
  searchPlaceholder: string;
  emptyLabel: string;
}): ReactElement {
  const selectedValues = new Set(values);
  const selectedOptions = options.filter(
    (option) => option.value !== "" && selectedValues.has(option.value),
  );
  const defaultOption = options.find((option) => option.value === "");
  const comboboxValue =
    selectedOptions.length === 0 && defaultOption
      ? [defaultOption]
      : selectedOptions;

  const updateSelection = (nextOptions: CanvasFilterOption[]): void => {
    const nextValues = nextOptions.map((option) => option.value);
    if (nextValues.includes("")) {
      onChange(values.length === 0 ? nextValues.filter(Boolean) : []);
      return;
    }
    onChange(nextValues);
  };

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger className="pr-1">
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
        <Combobox<CanvasFilterOption, true>
          multiple
          autoHighlight
          items={options}
          value={comboboxValue}
          onValueChange={(nextOptions) => updateSelection(nextOptions ?? [])}
          itemToStringLabel={(option) =>
            `${option.label} ${option.searchLabel ?? ""}`
          }
          itemToStringValue={(option) => option.value}
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
              {(option: CanvasFilterOption) => (
                <ComboboxItem
                  key={option.value || "default"}
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
