import type { ReactNode } from "react";

/**
 * A heading in the space's side column.
 *
 * Deliberately quieter than a pane's own title: the column is context beside
 * the log, and headings sized like the page's made it read as a second page.
 * Sticky, because the column shares the page's scroller and a heading that
 * leaves the screen takes the name of what you are reading with it.
 */
export function SideColumnHeading({ children }: { children: ReactNode }) {
  return (
    <h2 className="sticky top-0 z-10 bg-gray-1 px-3.5 pt-4 pb-1.5 font-semibold text-[11px] text-foreground/70 uppercase tracking-wider">
      {children}
    </h2>
  );
}
