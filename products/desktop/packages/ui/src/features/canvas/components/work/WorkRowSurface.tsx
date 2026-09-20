import { AutocompleteItem, type Button, cn } from "@posthog/quill";
import type { ComponentProps } from "react";

export function WorkRowSurface({
  optionValue,
  className,
  children,
  ...rest
}: ComponentProps<typeof Button> & { optionValue: string }) {
  return (
    <AutocompleteItem
      value={optionValue}
      className={cn(
        "w-full min-w-0 cursor-pointer pr-1 text-left data-selected:bg-fill-selected data-selected:text-foreground",
        "[&>span]:w-full [&>span]:min-w-0 [&>span]:justify-start [&>span]:gap-2 [&>span]:overflow-visible",
        "[&_svg_*]:text-inherit!",
        "ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0",
        className,
      )}
      {...(rest as ComponentProps<typeof AutocompleteItem>)}
    >
      {children}
    </AutocompleteItem>
  );
}
