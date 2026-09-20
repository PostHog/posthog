import type { ReactNode } from "react";

/**
 * A heading in the space's side column.
 *
 * Deliberately quieter than a pane's own title: the column is context beside
 * the log, and headings sized like the page's made it read as a second page.
 */
export function SideColumnHeading({ children }: { children: ReactNode }) {
  return (
    <h2 className="px-3.5 pt-4 pb-1.5 font-semibold text-[11px] text-foreground/70 uppercase tracking-wider">
      {children}
    </h2>
  );
}
