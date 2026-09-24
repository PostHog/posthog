import { XIcon } from "@phosphor-icons/react";
import { AutocompleteInput, InputGroupButton } from "@posthog/quill";
import type { Ref } from "react";

export function WorkSearchField({
  ref,
  query,
  matchCount,
  onClear,
  onClose,
}: {
  ref: Ref<HTMLInputElement>;
  query: string;
  matchCount: number;
  onClear: () => void;
  onClose: () => void;
}) {
  const hasQuery = query !== "";
  return (
    <div className="min-w-0 flex-1">
      <AutocompleteInput
        ref={ref}
        placeholder="Search recent…"
        aria-label="Search recent"
        className="h-6 text-[13px]"
        onKeyDown={(event) => {
          if (event.defaultPrevented || event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          if (hasQuery) onClear();
          else onClose();
        }}
        onBlur={() => {
          if (!hasQuery) onClose();
        }}
      >
        {hasQuery && (
          <span className="shrink-0 text-[11px] text-muted-foreground tabular-nums">
            {matchCount === 0 ? "No results" : matchCount}
          </span>
        )}
        <InputGroupButton
          size="icon-xs"
          aria-label={hasQuery ? "Clear search" : "Close search"}
          onMouseDown={(event) => event.preventDefault()}
          onClick={hasQuery ? onClear : onClose}
        >
          <XIcon size={12} />
        </InputGroupButton>
      </AutocompleteInput>
    </div>
  );
}
