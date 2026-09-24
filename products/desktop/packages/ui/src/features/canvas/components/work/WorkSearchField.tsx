import { XIcon } from "@phosphor-icons/react";
import { AutocompleteInput, InputGroupButton } from "@posthog/quill";
import { forwardRef } from "react";

export const WorkSearchField = forwardRef<
  HTMLInputElement,
  {
    query: string;
    matchCount: number;
    placeholder: string;
    searchLabel: string;
    onClear: () => void;
    onClose: () => void;
  }
>(function WorkSearchField(
  { query, matchCount, placeholder, searchLabel, onClear, onClose },
  ref,
) {
  const hasQuery = query !== "";
  return (
    <div className="min-w-0 flex-1">
      <AutocompleteInput
        ref={ref}
        placeholder={placeholder}
        aria-label={searchLabel}
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
});
