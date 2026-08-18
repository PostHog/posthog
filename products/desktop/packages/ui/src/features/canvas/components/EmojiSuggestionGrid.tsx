import { Autocomplete as BaseAutocomplete } from "@base-ui/react/autocomplete";
import {
  Autocomplete,
  AutocompleteItem,
  AutocompleteList,
} from "@posthog/quill";
import type { EmojiSuggestion } from "@posthog/ui/features/canvas/utils/emojiSuggestions";
import type { ReactElement } from "react";

const COLUMN_COUNT = 6;

export function EmojiSuggestionGrid({
  suggestions,
  highlightedIndex,
  onHighlight,
  onSelect,
  registerItem,
}: {
  suggestions: EmojiSuggestion[];
  highlightedIndex: number;
  onHighlight: (index: number) => void;
  onSelect: (suggestion: EmojiSuggestion) => void;
  registerItem?: (index: number, element: HTMLElement | null) => void;
}): ReactElement {
  const rows: EmojiSuggestion[][] = [];
  for (let index = 0; index < suggestions.length; index += COLUMN_COUNT) {
    rows.push(suggestions.slice(index, index + COLUMN_COUNT));
  }

  return (
    <div className="absolute bottom-full left-0 z-50 mb-1 w-64 overflow-hidden rounded-md border border-border bg-card shadow-lg">
      <Autocomplete
        inline
        grid
        mode="none"
        items={suggestions}
        itemToStringValue={(suggestion) => suggestion.name}
      >
        <AutocompleteList
          aria-label="Choose an emoji"
          className="max-h-56 space-y-1 overflow-y-auto"
        >
          {rows.map((row, rowIndex) => (
            <BaseAutocomplete.Row
              key={row[0]?.id ?? rowIndex}
              className="grid grid-cols-6 gap-1"
            >
              {row.map((suggestion, columnIndex) => {
                const index = rowIndex * COLUMN_COUNT + columnIndex;
                return (
                  <AutocompleteItem
                    key={suggestion.id}
                    value={suggestion}
                    nativeButton
                    ref={(element) => registerItem?.(index, element)}
                    aria-label={`:${suggestion.name}:`}
                    data-attr="comment-emoji-suggestion"
                    title={`:${suggestion.name}:`}
                    onMouseDown={(event) => event.preventDefault()}
                    onMouseEnter={() => onHighlight(index)}
                    onClick={() => onSelect(suggestion)}
                    className={`h-8 justify-center px-0 text-lg ${
                      index === highlightedIndex ? "bg-fill-selected" : ""
                    }`}
                  >
                    {suggestion.imageUrl ? (
                      <img
                        src={suggestion.imageUrl}
                        alt=""
                        className="size-5 object-contain"
                      />
                    ) : (
                      suggestion.emoji
                    )}
                  </AutocompleteItem>
                );
              })}
            </BaseAutocomplete.Row>
          ))}
        </AutocompleteList>
      </Autocomplete>
    </div>
  );
}
