import { ChatCircleIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { type RefObject, useCallback, useEffect, useState } from "react";

/** A text selection turned into a markdown blockquote for the chat composer. */
export function quoteSelection(text: string): string {
  const quoted = text
    .trim()
    .split("\n")
    .map((line) => `> ${line.trim()}`)
    .join("\n");
  return `${quoted}\n\n`;
}

interface AskAboutSelectionProps {
  /** Selections outside this container are ignored. */
  containerRef: RefObject<HTMLElement | null>;
  onAsk: (selectedText: string) => void;
}

/**
 * The highlight-to-ask affordance: selecting text inside the container floats
 * an "Ask about this" button by the selection; clicking it hands the passage
 * to the chat panel as a quote. Selection state is read on mouseup rather than
 * per selectionchange so the button doesn't chase a drag in progress.
 */
export function AskAboutSelection({
  containerRef,
  onAsk,
}: AskAboutSelectionProps) {
  const [anchor, setAnchor] = useState<{
    top: number;
    left: number;
    text: string;
  } | null>(null);

  const readSelection = useCallback(() => {
    const container = containerRef.current;
    const selection = window.getSelection();
    if (!container || !selection || selection.isCollapsed) {
      setAnchor(null);
      return;
    }
    const range = selection.getRangeAt(0);
    if (!container.contains(range.commonAncestorContainer)) {
      setAnchor(null);
      return;
    }
    const text = selection.toString().trim();
    if (!text) {
      setAnchor(null);
      return;
    }
    const rect = range.getBoundingClientRect();
    setAnchor({
      // Above the selection, clamped inside the viewport.
      top: Math.max(8, rect.top - 36),
      left: Math.min(
        Math.max(8, rect.left + rect.width / 2),
        window.innerWidth - 90,
      ),
      text,
    });
  }, [containerRef]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const clear = () => {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed) setAnchor(null);
    };
    // The button is pinned to viewport coordinates captured once, so scrolling
    // the report would strand it away from its passage. Scrolling doesn't
    // collapse the selection, so `clear` never fires here — dismiss directly.
    const dismissOnScroll = () => setAnchor(null);
    container.addEventListener("mouseup", readSelection);
    container.addEventListener("scroll", dismissOnScroll);
    // Collapsing the selection anywhere (click, Esc, typing) dismisses the button.
    document.addEventListener("selectionchange", clear);
    return () => {
      container.removeEventListener("mouseup", readSelection);
      container.removeEventListener("scroll", dismissOnScroll);
      document.removeEventListener("selectionchange", clear);
    };
  }, [containerRef, readSelection]);

  if (!anchor) return null;

  return (
    <div
      className="-translate-x-1/2 fixed z-50"
      style={{ top: anchor.top, left: anchor.left }}
    >
      <Button
        type="button"
        variant="primary"
        size="sm"
        className="gap-1 shadow-md"
        // preventDefault stops the mousedown from collapsing the selection,
        // which would unmount the button before the click lands. Running the
        // action on click (not mousedown) also lets Enter/Space activate it when
        // focused; the quote comes from the captured anchor, not the live
        // selection, so it stays correct on the mouse path.
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => {
          onAsk(anchor.text);
          setAnchor(null);
          window.getSelection()?.removeAllRanges();
        }}
      >
        <ChatCircleIcon size={13} />
        Ask about this
      </Button>
    </div>
  );
}
