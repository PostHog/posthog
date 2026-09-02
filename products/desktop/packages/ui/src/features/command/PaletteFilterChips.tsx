import { cn } from "@posthog/quill";
import type { FeedQueryKeyChip } from "@posthog/ui/features/command/useFeedQueryCommands";
import { useState } from "react";

export function PaletteFilterChips({
  chips,
  collapsedCount,
}: {
  chips: FeedQueryKeyChip[];
  collapsedCount: number;
}) {
  const [expanded, setExpanded] = useState(false);

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
