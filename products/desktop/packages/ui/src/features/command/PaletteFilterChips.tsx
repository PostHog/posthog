import { cn } from "@posthog/quill";
import type { FeedQueryKeyChip } from "@posthog/ui/features/command/useFeedQueryCommands";
import { useEffect, useState } from "react";

/**
 * The filter catalog as a chip strip under the palette input, not list rows:
 * twelve rows of keys buried the results being searched. Expanded, every key
 * shows its hint inline, because those hints are the vocabulary the query
 * language has to be learned from.
 */
export function PaletteFilterChips({
  chips,
  collapsedCount,
  filtering,
}: {
  chips: FeedQueryKeyChip[];
  collapsedCount: number;
  /** A bare word is being typed, so the catalog is already narrowed. */
  filtering: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  // Collapse when the full catalog comes back, so it doesn't reopen three rows
  // deep after a narrowed strip.
  useEffect(() => {
    if (filtering) setExpanded(false);
  }, [filtering]);

  const overflow = Math.max(0, chips.length - collapsedCount);
  const open = expanded || overflow === 0;
  const visible = open ? chips : chips.slice(0, collapsedCount);

  return (
    <div
      className={cn(
        "flex gap-1.5 border-(--gray-a4) border-b px-3 py-1.5",
        open ? "flex-wrap items-start" : "items-center",
      )}
    >
      <span className="shrink-0 select-none py-1 text-(--gray-9) text-[11px]">
        Filter by
      </span>
      {visible.map((chip) => (
        <button
          key={chip.label}
          type="button"
          className={cn(
            "flex h-[22px] shrink-0 items-center rounded-md border border-(--gray-a6) bg-(--gray-a2) px-2",
            "text-[11.5px]",
            "hover:border-(--gray-a8) hover:bg-(--gray-a4)",
            "focus-visible:-outline-offset-1 focus-visible:outline focus-visible:outline-(--focus-8) focus-visible:outline-2",
          )}
          onMouseDown={(e) => e.preventDefault()}
          onClick={chip.apply}
        >
          {/* Centering the row, then baseline-aligning inside it: the mono key
              and the proportional hint have different glyph-box heights, so
              centering each one leaves them a pixel apart. */}
          <span className="flex items-baseline gap-1.5 leading-none">
            <span className="font-mono text-(--blue-11) text-[11px]">
              {chip.label}
            </span>
            {open && chip.hint && (
              <span className="text-(--gray-9)">{chip.hint}</span>
            )}
          </span>
        </button>
      ))}
      {overflow > 0 && (
        <button
          type="button"
          className={cn(
            "h-[22px] shrink-0 rounded-md px-2 text-(--gray-11) text-[11.5px] leading-none",
            "hover:bg-(--gray-a3) hover:text-(--gray-12)",
            "focus-visible:-outline-offset-1 focus-visible:outline focus-visible:outline-(--focus-8) focus-visible:outline-2",
          )}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "Show fewer" : `${overflow} more`}
        </button>
      )}
    </div>
  );
}
