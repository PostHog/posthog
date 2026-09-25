import { AutocompleteClear, AutocompleteInput, Kbd } from "@posthog/quill";
import { useSidebarSearchFocus } from "@posthog/ui/features/canvas/hooks/useSidebarSearchFocus";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import {
  forwardRef,
  type ReactElement,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  useRef,
} from "react";

interface SidebarSearchHeaderProps {
  title: string;
  actions?: ReactNode;
  query: string;
  placeholder: string;
  searchLabel: string;
  onClear: () => void;
  onKeyDown?: (event: ReactKeyboardEvent<HTMLInputElement>) => void;
}

export function SidebarSearchHeader({
  title,
  actions,
  query,
  placeholder,
  searchLabel,
  onClear,
  onKeyDown,
}: SidebarSearchHeaderProps): ReactElement {
  const searchRef = useRef<HTMLInputElement | null>(null);
  useSidebarSearchFocus(searchRef);

  return (
    <>
      <ChromeBar actions={actions}>
        <h2 className="font-bold text-base">{title}</h2>
      </ChromeBar>
      <div className="shrink-0 px-2 pt-2">
        <SidebarSearchInput
          ref={searchRef}
          query={query}
          placeholder={placeholder}
          searchLabel={searchLabel}
          onClear={onClear}
          onKeyDown={onKeyDown}
        />
      </div>
    </>
  );
}

export const SidebarSearchInput = forwardRef<
  HTMLInputElement,
  {
    query: string;
    placeholder: string;
    searchLabel: string;
    onClear: () => void;
    onKeyDown?: (event: ReactKeyboardEvent<HTMLInputElement>) => void;
    className?: string;
  }
>(function SidebarSearchInput(
  { query, placeholder, searchLabel, onClear, onKeyDown, className },
  ref,
) {
  return (
    <div className={className}>
      <AutocompleteInput
        ref={ref}
        placeholder={placeholder}
        aria-label={searchLabel}
        showSearchIcon={false}
        className="h-7 text-[13px] hover:bg-fill-hover"
        onKeyDown={(event) => {
          onKeyDown?.(event);
          if (
            event.defaultPrevented ||
            event.key !== "Escape" ||
            query === ""
          ) {
            return;
          }
          event.preventDefault();
          event.stopPropagation();
          onClear();
        }}
      >
        {query === "" ? (
          <Kbd className="-mr-0.5 shrink-0">
            {formatHotkey(SHORTCUTS.FOCUS_SIDEBAR_SEARCH)}
          </Kbd>
        ) : (
          <AutocompleteClear
            tabIndex={0}
            aria-label="Clear search"
            onClick={onClear}
          />
        )}
      </AutocompleteInput>
    </div>
  );
});
