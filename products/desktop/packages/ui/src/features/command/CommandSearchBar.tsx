import { MagnifyingGlass } from "@phosphor-icons/react";
import { Kbd } from "@posthog/quill";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";

/**
 * The search field over the content pane — a target you aim at, not an icon you
 * hunt for. It opens the command menu rather than typing into anything, so it is
 * a button wearing a field's clothes: the placeholder and the shortcut hint are
 * what tell you the menu is behind it.
 *
 * It fills the title bar's middle, which is the content column's width, and caps
 * itself so a wide window leaves it centred rather than stretched.
 */
export function CommandSearchBar({ onClick }: { onClick: () => void }) {
  return (
    // The row is a window-drag region; the field has to opt out of it or the
    // press that should open the menu drags the window instead.
    <div className="mt-px min-w-0 flex-1 px-3">
      <button
        type="button"
        aria-label="Search"
        onClick={onClick}
        className="no-drag mx-auto flex h-7 w-full max-w-120 items-center gap-2 rounded-sm bg-fill-hover pr-1 pl-2 hover:bg-fill-selected dark:hover:bg-input/80"
      >
        <MagnifyingGlass size={14} className="shrink-0" />
        <span className="min-w-0 flex-1 truncate text-left text-[13px]">
          Search
        </span>
        <Kbd className="shrink-0 rounded-xs opacity-60">
          {formatHotkey(SHORTCUTS.COMMAND_MENU)}
        </Kbd>
      </button>
    </div>
  );
}
