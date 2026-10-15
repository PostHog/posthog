import { ToggleGroup, ToggleGroupItem } from "@posthog/quill";
import {
  isObjectSort,
  OBJECT_SORT_OPTIONS,
  type ObjectSort,
} from "@posthog/ui/features/command/objectSort";
import type { ReactNode } from "react";

// Quill toggles sink 2px when pressed, which reads as misalignment in a thin bar.
const SORT_ITEM_CLASS =
  "h-5 translate-y-0 px-2 text-[11px] text-muted-foreground shadow-none data-[pressed]:translate-y-0 data-[pressed]:border-(--accent-9) data-[pressed]:bg-(--accent-3) data-[pressed]:text-(--accent-11) data-[pressed]:shadow-none";

/** The palette's status line: the match summary, and the sort while one applies. */
export function PaletteSortBar({
  sort,
  onSortChange,
  children,
}: {
  /** Null hides the sort control. */
  sort: ObjectSort | null;
  onSortChange: (sort: ObjectSort) => void;
  children?: ReactNode;
}) {
  return (
    <div className="flex min-h-7 items-center gap-2 border-border border-b px-3 py-1 text-subtle-foreground text-xs tabular-nums">
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {sort && (
        <div className="flex shrink-0 items-center gap-1.5">
          <span className="text-[11px]">Sort by</span>
          <ToggleGroup
            value={[sort]}
            onValueChange={(next: string[]) => {
              const picked = next[0];
              if (isObjectSort(picked) && picked !== sort) onSortChange(picked);
            }}
            aria-label="Sort results"
          >
            {OBJECT_SORT_OPTIONS.map((option) => (
              <ToggleGroupItem
                key={option.value}
                value={option.value}
                size="sm"
                variant="outline"
                className={SORT_ITEM_CLASS}
                // Keep focus in the search field, so typing continues after a click.
                onMouseDown={(event) => event.preventDefault()}
              >
                {option.label}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
        </div>
      )}
    </div>
  );
}
