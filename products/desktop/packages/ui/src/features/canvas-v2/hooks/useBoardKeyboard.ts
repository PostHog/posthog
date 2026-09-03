import {
  type BoardBox,
  fitToContent,
  zoomTo,
} from "@posthog/core/canvas-v2/boardGeometry";
import type { CanvasV2Viewport } from "@posthog/shared";
import { readPaneRect } from "@posthog/ui/features/canvas-v2/interaction/useBoardPointer";
import { useEffect, useRef } from "react";

export interface UseBoardKeyboardOptions {
  /** False while a dialog or another surface owns the keyboard. */
  enabled?: boolean;
  paneRef: React.RefObject<HTMLElement | null>;
  fragments: readonly BoardBox[];
  viewport: CanvasV2Viewport;
  setViewport: (viewport: CanvasV2Viewport) => void;
  selectedId: string | null;
  onDeleteSelected: (id: string) => void;
  onClearSelection: () => void;
  onUndo: () => void;
}

/** Board shortcuts. They never fire while the person is typing. */
export function useBoardKeyboard(options: UseBoardKeyboardOptions): void {
  const latest = useRef(options);
  latest.current = options;

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      const current = latest.current;
      if (current.enabled === false) return;
      if (isTypingTarget(event.target)) return;

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        current.onUndo();
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const pane = readPaneRect(current.paneRef.current);

      switch (event.key) {
        case "Delete":
        case "Backspace":
          if (!current.selectedId) return;
          event.preventDefault();
          current.onDeleteSelected(current.selectedId);
          return;
        case "Escape":
          current.onClearSelection();
          return;
        case "0":
          event.preventDefault();
          current.setViewport(zoomTo(current.viewport, 1, pane));
          return;
        case "1":
          event.preventDefault();
          current.setViewport(fitToContent(current.fragments, pane));
          return;
        default:
          return;
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}

/**
 * The iframe counts as typing: fragment code owns its own keyboard, and the
 * host must not delete a fragment while someone types inside one.
 */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    tag === "IFRAME"
  ) {
    return true;
  }
  return target.isContentEditable;
}
