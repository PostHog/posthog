import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { useHotkeys } from "react-hotkeys-hook";

/**
 * Renders nothing — claims Cmd/Ctrl+W wherever BrowserTabStrip isn't mounted.
 *
 * The strip's own CLOSE_TAB handler preventDefaults unconditionally, because
 * otherwise the key reaches Electron's Window ▸ Close role (`{ role:
 * "windowMenu" }` in the host menu) and closes the window, losing everything in
 * it. Any route that renders the app without the strip — the whole channels
 * layout, and the settings shell either way — needs someone else to hold the key.
 *
 * The task view's editor panel keeps closing its own tab from
 * usePanelKeyboardShortcuts; that handler runs too, and this one only swallows.
 */
export function TabShortcutFallback({ enabled }: { enabled: boolean }) {
  useHotkeys(
    SHORTCUTS.CLOSE_TAB,
    (event) => {
      event.preventDefault();
    },
    { enabled, enableOnFormTags: true, enableOnContentEditable: true },
  );

  return null;
}
