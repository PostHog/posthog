import { CaretDown } from "@phosphor-icons/react";
import type { ScoutTagOption } from "@posthog/core/scouts/scoutTags";
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@posthog/quill";

/**
 * Multi-select tag filter for the fleet list. Any-of, matching the config API's
 * `tags` overlap filter — picking a second tag widens the list rather than
 * narrowing it to scouts carrying both.
 */
export function ScoutTagsFilter({
  options,
  selected,
  onToggle,
  onClear,
}: {
  options: ScoutTagOption[];
  selected: string[];
  onToggle: (tag: string) => void;
  onClear: () => void;
}) {
  const label =
    selected.length === 0
      ? "Any tag"
      : selected.length === 1
        ? selected[0]
        : `${selected.length} tags`;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label="Filter scouts by tag"
            className="w-full justify-between"
          >
            <span className="min-w-0 truncate">{label}</span>
            <CaretDown
              size={10}
              weight="bold"
              className="shrink-0 text-muted-foreground"
            />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={6}
        className="min-w-(--anchor-width)"
      >
        {options.map((option) => (
          <DropdownMenuCheckboxItem
            key={option.tag}
            checked={selected.includes(option.tag)}
            closeOnClick={false}
            onCheckedChange={() => onToggle(option.tag)}
          >
            <span className="min-w-0 truncate">{option.tag}</span>
            <span className="ml-auto pl-3 text-muted-foreground tabular-nums">
              {option.count}
            </span>
          </DropdownMenuCheckboxItem>
        ))}
        {selected.length > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={onClear}>Clear tags</DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
