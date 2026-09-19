import { AutocompleteItem, type Button, cn } from "@posthog/quill";
import type { ComponentProps } from "react";

/**
 * A row in the Work column, as the keyboard sees it.
 *
 * Every row is an Autocomplete option, so ↑/↓/⏎ walk the whole column while
 * the search box keeps focus — the same contract the space list and the
 * activity feed hold. The classes mirror `SpaceRowSurface`'s, so a row here
 * and a row there cannot drift apart.
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
        // quill wraps an option's children in its own flex row; widening it is
        // what lets a name truncate and a trailing mark sit at the row's edge.
        "[&>span]:w-full [&>span]:min-w-0 [&>span]:justify-start [&>span]:gap-2 [&>span]:overflow-visible",
        // A highlighted option has its contents repainted down to the `<path>`
        // that `fill: currentColor` resolves against, which drops a glyph's own
        // colour. Sending the marks back to their icon keeps them under the
        // pointer and the keyboard.
        "[&_svg_*]:text-inherit!",
        // quill highlights an option with an offset focus ring, which reads as
        // a stray outline on a sidebar row. Same fill the rows hover to.
        "ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0",
        className,
      )}
      {...(rest as ComponentProps<typeof AutocompleteItem>)}
    >
      {children}
    </AutocompleteItem>
  );
}
