import { AutocompleteItem, type Button, cn } from "@posthog/quill";
import type { ComponentProps } from "react";

/**
 * A list row as an autocomplete option, which is what keeps it on the keyboard's
 * arrow path.
 *
 * The three overrides below answer quill's own defaults, which `AutocompleteItem`
 * does not parameterize: it wraps its children in a centered, truncating span,
 * it colours a highlighted option's contents, and it draws a ring and a border
 * on the highlight. A row supplies its own layout, its own marks and its own
 * hover fill, so each default has to give way. The `[&>span]` rules therefore
 * depend on that wrapper staying one span deep.
 */
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
