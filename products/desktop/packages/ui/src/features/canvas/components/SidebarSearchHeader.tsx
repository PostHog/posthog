import { AutocompleteClear, AutocompleteInput, Kbd } from "@posthog/quill";
import { useSidebarSearchStore } from "@posthog/ui/features/canvas/stores/sidebarSearchStore";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import {
  type ReactElement,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  useEffect,
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

function focusSearch(input: HTMLInputElement): void {
  input.focus();
  input.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Home", bubbles: true }),
  );
  input.select();
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
  const focusRequest = useSidebarSearchStore((state) => state.focusRequest);

  useEffect(() => {
    if (focusRequest === 0) return;
    const input = searchRef.current;
    if (!input || input.closest("[inert]")) return;
    // Claim after the inert guard so an offscreen header leaves the request for
    // the visible one, and so each request focuses a single header once.
    if (!useSidebarSearchStore.getState().claimFocus(focusRequest)) return;
    focusSearch(input);
  }, [focusRequest]);

  return (
    <>
      <ChromeBar actions={actions}>
        <h2 className="font-bold text-base">{title}</h2>
      </ChromeBar>
      <div className="shrink-0 px-2 pt-2">
        <AutocompleteInput
          ref={searchRef}
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
    </>
  );
}
