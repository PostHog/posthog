import {
  cn,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@posthog/quill";
import type { CanvasFilterOption } from "@posthog/ui/features/canvas/components/canvasFilterSelection";
import type { ReactElement } from "react";

export function CanvasFilterRadioSubmenu({
  label,
  options,
  value,
  defaultValue,
  onChange,
}: {
  label: string;
  options: readonly CanvasFilterOption[];
  value: string;
  defaultValue: string;
  onChange: (value: string) => void;
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
        <DropdownMenuRadioGroup value={value} onValueChange={onChange}>
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
