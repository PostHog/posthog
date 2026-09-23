import { Button, cn } from "@posthog/quill";
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
        "flex gap-0.5 border-border border-b px-2.5 py-1",
        open ? "flex-wrap items-start" : "items-center",
      )}
    >
      <span className="shrink-0 select-none px-1 py-0.5 text-[11px] text-subtle-foreground">
        Filter by
      </span>
      {visible.map((chip) => (
        <Button
          key={chip.label}
          size="xs"
          className="shrink-0 gap-1.5 font-normal"
          onMouseDown={(e) => e.preventDefault()}
          onClick={chip.apply}
        >
          <span className="font-mono text-[11px] text-muted-foreground">
            {chip.label}
          </span>
          {open && chip.hint && (
            <span className="text-[11px] text-subtle-foreground">
              {chip.hint}
            </span>
          )}
        </Button>
      ))}
      {overflow > 0 && (
        <Button
          size="xs"
          className="shrink-0 font-normal text-[11px] text-subtle-foreground"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "Show fewer" : `${overflow} more`}
        </Button>
      )}
    </div>
  );
}
