import { useEffect } from "react";

/**
 * While a blocking announcement modal is on stage, swallow every keyboard
 * event at the window capture phase. The dialog overlay already blocks the
 * pointer, but the app's shortcuts (command menu, tab switching, hotkeys)
 * listen on document or window and fire regardless of the modal — capturing
 * at the window, ahead of them all, starves them. The modal itself stays
 * fully operable: Tab traversal and Enter/Space activation of the focused
 * button or link are native default actions, not listener-driven. Electron
 * menu accelerators live in the main process and are out of reach here.
 */
export function useBlockingKeyboardIsolation(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const swallow = (event: KeyboardEvent) => {
      event.stopImmediatePropagation();
    };
    const options = { capture: true } as const;
    window.addEventListener("keydown", swallow, options);
    window.addEventListener("keyup", swallow, options);
    window.addEventListener("keypress", swallow, options);
    return () => {
      window.removeEventListener("keydown", swallow, options);
      window.removeEventListener("keyup", swallow, options);
      window.removeEventListener("keypress", swallow, options);
    };
  }, [active]);
}
