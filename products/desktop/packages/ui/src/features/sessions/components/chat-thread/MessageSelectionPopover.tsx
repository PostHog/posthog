import {
  ListChecksIcon,
  NotePencilIcon,
  SpinnerIcon,
} from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import type { ChannelDocumentKind, Task } from "@posthog/shared/domain-types";
import { useSpaceDocsPanelStore } from "@posthog/ui/features/space-docs/spaceDocsPanelStore";
import {
  DEFAULT_DOC_NAMES,
  useCaptureToChannelDocument,
} from "@posthog/ui/features/space-docs/useChannelDocuments";
import { toast } from "@posthog/ui/primitives/toast";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const MIN_SELECTION_LENGTH = 4;
const POPOVER_HEIGHT_OFFSET = 40;
const POPOVER_EDGE_MARGIN = 8;

interface ActiveSelection {
  text: string;
  rect: DOMRect;
}

/**
 * Read the current selection, accepting it only when it's a non-trivial text
 * range that starts and ends inside the same `[data-selectable-message]`
 * element within `root` — so cross-message drags, selections in other panes,
 * and selections inside a still-streaming bubble (whose text reflows under
 * the cursor) don't get a popover.
 */
function readSelection(root: HTMLElement | null): ActiveSelection | null {
  if (!root) return null;
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0)
    return null;
  const text = selection.toString();
  if (text.trim().length < MIN_SELECTION_LENGTH) return null;

  const elementOf = (node: Node | null): Element | null =>
    node instanceof Element ? node : (node?.parentElement ?? null);
  const anchorMessage = elementOf(selection.anchorNode)?.closest(
    "[data-selectable-message]",
  );
  const focusMessage = elementOf(selection.focusNode)?.closest(
    "[data-selectable-message]",
  );
  if (!anchorMessage || anchorMessage !== focusMessage) return null;
  if (!root.contains(anchorMessage)) return null;
  if (anchorMessage.closest('[data-streaming="true"]')) return null;

  const rect = selection.getRangeAt(0).getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return null;
  return { text, rect };
}

/**
 * Floating actions over a text selection in the chat thread: capture the
 * highlighted text into the space's shared todo/plan doc. Captures land in the
 * task's channel, falling back to the personal #me channel for tasks without
 * one; success opens the space docs sidepanel on the captured doc.
 */
export function MessageSelectionPopover({
  rootRef,
  task,
}: {
  rootRef: React.RefObject<HTMLElement | null>;
  task?: Task;
}) {
  const [active, setActive] = useState<ActiveSelection | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const capture = useCaptureToChannelDocument();
  const openPanel = useSpaceDocsPanelStore((s) => s.openPanel);
  const isCapturing = capture.isPending;

  useEffect(() => {
    let frame = 0;
    const refresh = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() =>
        setActive(readSelection(rootRef.current)),
      );
    };
    // Selections re-fire selectionchange constantly while dragging; the rAF
    // coalesces those, and mouseup catches the final rect.
    document.addEventListener("selectionchange", refresh);
    document.addEventListener("mouseup", refresh);
    // Any scroll or resize would leave the popover floating over the wrong
    // text (windowed rows even unmount), so dismiss instead of tracking.
    const dismiss = () => setActive(null);
    window.addEventListener("scroll", dismiss, { capture: true });
    window.addEventListener("resize", dismiss);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") dismiss();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("selectionchange", refresh);
      document.removeEventListener("mouseup", refresh);
      window.removeEventListener("scroll", dismiss, { capture: true });
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [rootRef]);

  const handleCapture = useCallback(
    (docKind: ChannelDocumentKind) => {
      if (!active || isCapturing) return;
      capture.mutate(
        {
          channelId: task?.channel ?? undefined,
          docKind,
          text: active.text,
          source: task
            ? {
                label: task.title || "task",
                url: `posthog-code://task/${task.id}`,
              }
            : undefined,
        },
        {
          onSuccess: ({ document, channelId }) => {
            toast.success(`Added to ${document.name}`);
            openPanel({ channelId, docKind });
            window.getSelection()?.removeAllRanges();
            setActive(null);
          },
          onError: (error) => {
            toast.error(`Couldn't add to ${DEFAULT_DOC_NAMES[docKind]}`, {
              description:
                error instanceof Error ? error.message : String(error),
            });
          },
        },
      );
    },
    [active, capture, isCapturing, openPanel, task],
  );

  if (!active) return null;

  const width = 240;
  const left = Math.min(
    Math.max(
      active.rect.left + active.rect.width / 2 - width / 2,
      POPOVER_EDGE_MARGIN,
    ),
    window.innerWidth - width - POPOVER_EDGE_MARGIN,
  );
  const top = Math.max(
    active.rect.top - POPOVER_HEIGHT_OFFSET,
    POPOVER_EDGE_MARGIN,
  );

  return createPortal(
    <div
      ref={popoverRef}
      role="toolbar"
      aria-label="Selection actions"
      className="fixed z-50 flex items-center gap-0.5 rounded-md border border-border bg-popover p-0.5 shadow-md"
      style={{ top, left, width: "max-content" }}
      // Keep the selection alive: a default mousedown would collapse it
      // before the click handler runs.
      onMouseDown={(event) => event.preventDefault()}
    >
      {isCapturing ? (
        <div className="flex items-center gap-1.5 px-2 py-1 text-sm">
          <SpinnerIcon size={14} className="animate-spin" />
          Adding…
        </div>
      ) : (
        <>
          <Button
            variant="default"
            size="sm"
            onClick={() => handleCapture("todo")}
          >
            <ListChecksIcon size={14} />
            Add to todos
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={() => handleCapture("plan")}
          >
            <NotePencilIcon size={14} />
            Add to plan
          </Button>
        </>
      )}
    </div>,
    document.body,
  );
}
